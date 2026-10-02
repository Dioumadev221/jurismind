"""Agent d'assistance sur un dossier (F7).

Trois services : répondre à une question, résumer le dossier, en dresser la chronologie.

Le graphe est **volontairement déterministe** : c'est le code qui décide des étapes et qui
lit la base ; le modèle ne sert qu'à deux choses, comprendre la demande et rédiger. Sur un
modèle local de 3 milliards de paramètres, laisser l'IA choisir librement ses outils donne
des enchaînements erratiques et lents ; et surtout, une date ou un montant lus en base ne
peuvent pas être inventés.

    comprendre ──► collecter ──┬─► question ────┐
                               ├─► resume ──────┼─► journaliser ──► fin
                               └─► chronologie ─┘
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from enum import StrEnum
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from jurismind.agents.commun import (
    ReponseAgent,
    chiffres_douteux,
    inscrire_au_journal,
    lire_json,
    texte_attendu,
)
from jurismind.agents.outils import Evenement, donnees_extraites, evenements_du_dossier, fiche_dossier
from jurismind.llm import Vitesse, modele_chat
from jurismind.rag import repondre
from jurismind.rag.verification import avoue_ignorance
from jurismind.retrieval import Filtres, rechercher

logger = logging.getLogger(__name__)

EXTRAITS_POUR_RESUME = 6


class Intention(StrEnum):
    QUESTION = "question"
    RESUME = "resume"
    CHRONOLOGIE = "chronologie"


# Mots qui suffisent à décider sans déranger le modèle : plus rapide et plus sûr.
MOTS_RESUME = ("résume", "resume", "synthèse", "synthese", "point sur", "où en est", "ou en est")
MOTS_CHRONOLOGIE = ("chronologie", "historique", "déroulé", "deroule", "frise", "étapes", "etapes")

CONSIGNE_ROUTAGE = """Classe la demande d'un avocat sur un de ses dossiers.

Demande : {demande}

Réponds uniquement par ce JSON : {{"intention": "question" ou "resume" ou "chronologie"}}
- "resume" : il veut une synthèse du dossier.
- "chronologie" : il veut la suite des événements dans le temps.
- "question" : il pose une question précise.
"""

CONSIGNE_RESUME = """Tu rédiges la synthèse d'un dossier pour l'avocat qui le suit.

Fiche du dossier (données du cabinet, fiables) :
{fiche}

Valeurs extraites des actes :
{extraits_structures}

Derniers événements :
{evenements}

Passages des pièces :
{sources}

Rédige une synthèse de 5 phrases au maximum : les parties, l'objet, où en est la procédure,
les montants en jeu, la prochaine étape si elle ressort des pièces.
N'invente aucun montant ni aucune date : reprends ceux fournis ci-dessus.

Réponds uniquement par ce JSON : {{"resume": "…"}}
"""


class Etat(TypedDict, total=False):
    """Ce que le graphe se transmet d'une étape à l'autre."""

    utilisateur_id: int
    dossier_id: int
    demande: str
    intention: str
    fiche: dict[str, Any]
    evenements: list[Evenement]
    reponse: str
    citations: list[dict[str, Any]]
    abstention: bool
    secondes: float


def deviner_intention(demande: str) -> Intention | None:
    """Décision sans modèle quand la demande est explicite (ou vide)."""
    texte = demande.strip().lower()
    if not texte:
        return Intention.RESUME
    if any(mot in texte for mot in MOTS_CHRONOLOGIE):
        return Intention.CHRONOLOGIE
    if any(mot in texte for mot in MOTS_RESUME):
        return Intention.RESUME
    return None


def construire_graphe(session: Session) -> Any:
    """Construit le graphe de l'agent pour une session donnée (donc pour un utilisateur donné)."""

    def comprendre(etat: Etat) -> dict[str, Any]:
        demande = etat.get("demande", "")
        intention = deviner_intention(demande)
        if intention is None:
            brut = str(
                modele_chat(Vitesse.RAPIDE, json=True)
                .invoke(CONSIGNE_ROUTAGE.format(demande=demande))
                .content
            )
            valeur = str(lire_json(brut).get("intention", "")).strip().lower()
            intention = Intention(valeur) if valeur in set(Intention) else Intention.QUESTION
        logger.info("Intention retenue : %s", intention)
        return {"intention": str(intention)}

    def collecter(etat: Etat) -> dict[str, Any]:
        fiche = fiche_dossier(session, etat["dossier_id"])
        if fiche is None:
            # Dossier invisible pour cet utilisateur : on s'arrête là, sans rien révéler.
            return {"fiche": {}, "abstention": True, "reponse": "Dossier introuvable."}
        return {"fiche": fiche}

    def questionner(etat: Etat) -> dict[str, Any]:
        reponse = repondre(session, etat["demande"], filtres=Filtres(dossier_id=etat["dossier_id"]))
        return {
            "reponse": reponse.texte,
            "citations": [asdict(citation) for citation in reponse.citations],
            "abstention": reponse.abstention,
        }

    def chronologie(etat: Etat) -> dict[str, Any]:
        evenements = evenements_du_dossier(session, etat["dossier_id"])
        lignes = [evenement.ligne() for evenement in evenements]
        return {
            "evenements": evenements,
            "reponse": "\n".join(lignes) if lignes else "Aucun événement daté dans ce dossier.",
            "abstention": not lignes,
        }

    def resumer(etat: Etat) -> dict[str, Any]:
        dossier_id = etat["dossier_id"]
        evenements = evenements_du_dossier(session, dossier_id)
        extraits = rechercher(
            session,
            f"{etat['fiche'].get('intitule', '')} objet montants procédure",
            filtres=Filtres(dossier_id=dossier_id),
            limite=EXTRAITS_POUR_RESUME,
        )
        sources = "\n\n".join(
            f"[{rang}] {resultat.reference}\n{resultat.extrait.contenu}"
            for rang, resultat in enumerate(extraits, start=1)
        )
        invite = CONSIGNE_RESUME.format(
            fiche=json.dumps(etat["fiche"], ensure_ascii=False, default=str, indent=2),
            extraits_structures=json.dumps(
                donnees_extraites(session, dossier_id), ensure_ascii=False, default=str
            )[:1500],
            evenements="\n".join(evenement.ligne() for evenement in evenements[-12:]),
            sources=sources[:3000],
        )
        brut = str(modele_chat(Vitesse.RAPIDE, json=True).invoke(invite).content)
        texte = texte_attendu(lire_json(brut), "resume")

        # Mêmes garde-fous que pour une réponse : un chiffre non fourni n'est pas affiché.
        if not texte or avoue_ignorance(texte) or chiffres_douteux(texte, invite):
            logger.info("Résumé écarté par les vérifications : %r", texte[:120])
            return {
                "evenements": evenements,
                "reponse": "Je ne peux pas résumer ce dossier à partir des pièces disponibles.",
                "abstention": True,
            }
        return {
            "evenements": evenements,
            "reponse": texte,
            "citations": [
                {"numero": rang, "reference": resultat.reference, "extrait_id": resultat.extrait.id}
                for rang, resultat in enumerate(extraits, start=1)
            ],
            "abstention": False,
        }

    def journaliser(etat: Etat) -> dict[str, Any]:
        inscrire_au_journal(
            session,
            etat["utilisateur_id"],
            f"agent_dossier_{etat.get('intention', 'question')}",
            {
                "demande": etat.get("demande", "")[:300],
                "abstention": etat.get("abstention", False),
                "citations": len(etat.get("citations", [])),
            },
            dossier_id=etat.get("dossier_id"),
        )
        return {}

    def aiguiller(etat: Etat) -> str:
        if etat.get("abstention") and not etat.get("fiche"):
            return "journaliser"  # dossier inaccessible : on n'interroge rien
        return str(etat.get("intention", Intention.QUESTION))

    # Les surcharges de `add_node` n'acceptent pas un TypedDict `total=False` : seul le
    # constructeur du graphe échappe au contrôle, nos étapes restent typées.
    graphe: Any = StateGraph(Etat)
    graphe.add_node("comprendre", comprendre)
    graphe.add_node("collecter", collecter)
    graphe.add_node("question", questionner)
    graphe.add_node("resume", resumer)
    graphe.add_node("chronologie", chronologie)
    graphe.add_node("journaliser", journaliser)

    graphe.add_edge(START, "comprendre")
    graphe.add_edge("comprendre", "collecter")
    graphe.add_conditional_edges(
        "collecter",
        aiguiller,
        {
            "question": "question",
            "resume": "resume",
            "chronologie": "chronologie",
            "journaliser": "journaliser",
        },
    )
    for etape in ("question", "resume", "chronologie"):
        graphe.add_edge(etape, "journaliser")
    graphe.add_edge("journaliser", END)
    return graphe.compile()


def assister(session: Session, utilisateur_id: int, dossier_id: int, demande: str = "") -> ReponseAgent:
    """Point d'entrée de l'agent. La session porte les droits de l'utilisateur."""
    depart = time.perf_counter()
    etat_final = construire_graphe(session).invoke(
        Etat(utilisateur_id=utilisateur_id, dossier_id=dossier_id, demande=demande)
    )
    return ReponseAgent(
        intention=str(etat_final.get("intention", "")),
        texte=str(etat_final.get("reponse", "")),
        citations=list(etat_final.get("citations", [])),
        donnees={"evenements": [asdict(evenement) for evenement in etat_final.get("evenements", [])]},
        abstention=bool(etat_final.get("abstention", False)),
        secondes=time.perf_counter() - depart,
    )
