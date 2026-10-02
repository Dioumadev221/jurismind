"""Agent d'intelligence client (F6).

Trois services sur un client : sa fiche complète, une synthèse rédigée, ou une réponse à une
question précise cherchée dans tous ses dossiers.

Même principe que l'agent dossier (ADR 0005) : le graphe fixe les étapes, le code lit la base
et **calcule les points d'attention**, le modèle ne fait que rédiger. Un avocat à qui on
demande ce qui mérite son attention veut des faits vérifiables — un délai qui échoit le 24/08,
un courrier sans réponse depuis douze jours — pas les inquiétudes plausibles d'un modèle.

    comprendre ──► collecter ──┬─► question ─┐
                               ├─► synthese ─┼─► journaliser ──► fin
                               └─► fiche ────┘
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
from jurismind.agents.outils import (
    PointAttention,
    derniers_echanges,
    dossiers_du_client,
    elements_crm_du_client,
    fiche_client,
    montant_lisible,
    points_attention,
)
from jurismind.llm import Vitesse, modele_chat
from jurismind.rag import repondre
from jurismind.rag.verification import avoue_ignorance
from jurismind.retrieval import Filtres

logger = logging.getLogger(__name__)

ECHANGES_AFFICHES = 8


class Intention(StrEnum):
    QUESTION = "question"
    SYNTHESE = "synthese"
    FICHE = "fiche"


# Mots qui suffisent à décider sans déranger le modèle : plus rapide et plus sûr.
MOTS_FICHE = ("fiche", "chiffres", "attention", "alerte", "surveiller", "récapitulatif", "recapitulatif")
MOTS_SYNTHESE = (
    "synthèse",
    "synthese",
    "résume",
    "resume",
    "point sur",
    "le point",
    "où en est",
    "ou en est",
    "présente",
    "presente",
    "parle-moi",
    "360",
)

CONSIGNE_ROUTAGE = """Classe la demande d'un avocat au sujet d'un de ses clients.

Demande : {demande}

Réponds uniquement par ce JSON : {{"intention": "question" ou "synthese" ou "fiche"}}
- "fiche" : il veut les chiffres bruts et les points d'attention, sans rédaction.
- "synthese" : il veut un point rédigé sur la relation avec ce client.
- "question" : il pose une question précise dont la réponse est dans les pièces.
"""

CONSIGNE_SYNTHESE = """Tu fais le point sur un client pour l'avocat qui le suit.

Identité du client (données du cabinet, fiables) :
{fiche}

Ses dossiers :
{dossiers}

Derniers échanges :
{echanges}

Ce que le CRM en dit :
{crm}

Rédige un point de 4 phrases au maximum : qui est le client, ce qu'on traite pour lui, où
en sont les dossiers, l'état de la relation.
N'invente aucune date ni aucun nom de dossier : reprends ceux fournis ci-dessus.
Ne cite aucun montant et n'additionne rien : les dossiers et leurs enjeux sont affichés
sous ta synthèse, avec les chiffres exacts.
Ne parle ni de délais ni d'échéances : ils sont calculés ailleurs et affichés à part.

Réponds uniquement par ce JSON : {{"synthese": "…"}}
"""


class Etat(TypedDict, total=False):
    """Ce que le graphe se transmet d'une étape à l'autre."""

    utilisateur_id: int
    client_id: int
    demande: str
    intention: str
    fiche: dict[str, Any]
    dossiers: list[dict[str, Any]]
    echanges: list[dict[str, Any]]
    points: list[PointAttention]
    reponse: str
    citations: list[dict[str, Any]]
    abstention: bool


def deviner_intention(demande: str) -> Intention | None:
    """Décision sans modèle quand la demande est explicite (ou vide)."""
    texte = demande.strip().lower()
    if not texte:
        return Intention.SYNTHESE
    if any(mot in texte for mot in MOTS_FICHE):
        return Intention.FICHE
    if any(mot in texte for mot in MOTS_SYNTHESE):
        return Intention.SYNTHESE
    return None


def _en_texte(valeur: Any) -> str:
    return json.dumps(valeur, ensure_ascii=False, default=str, indent=2)


def _ligne_dossier(dossier: dict[str, Any]) -> str:
    """Un dossier en une ligne lisible : c'est la forme rendue à l'avocat et donnée au modèle."""
    enjeu = f", enjeu {montant_lisible(dossier['enjeu_fcfa'])} FCFA" if dossier["enjeu_fcfa"] else ""
    activite = (
        f", dernier mouvement le {dossier['derniere_activite']:%d/%m/%Y}"
        if dossier["derniere_activite"]
        else ", aucun mouvement"
    )
    return (
        f"{dossier['reference']} — {dossier['intitule']} ({dossier['statut']}, "
        f"{dossier['matiere']}{enjeu}{activite})"
    )


def _ligne_echange(echange: dict[str, Any]) -> str:
    return (
        f"{echange['date']:%d/%m/%Y} [{echange['dossier']}] {echange['sens']} "
        f"{echange['interlocuteur'] or ''} : {echange['objet'] or 'sans objet'}".rstrip()
    )


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
        fiche = fiche_client(session, etat["client_id"])
        if fiche is None:
            # Aucun dossier de ce client n'est ouvert à l'utilisateur : on s'arrête là.
            return {"fiche": {}, "abstention": True, "reponse": "Client introuvable."}
        dossiers = dossiers_du_client(session, etat["client_id"])
        return {
            "fiche": fiche,
            "dossiers": dossiers,
            "echanges": derniers_echanges(session, etat["client_id"], ECHANGES_AFFICHES),
            "points": points_attention(session, etat["client_id"], dossiers),
        }

    def questionner(etat: Etat) -> dict[str, Any]:
        """La question est cherchée dans tous les dossiers visibles de ce client, pas ailleurs."""
        reponse = repondre(session, etat["demande"], filtres=Filtres(client_id=etat["client_id"]))
        return {
            "reponse": reponse.texte,
            "citations": [asdict(citation) for citation in reponse.citations],
            "abstention": reponse.abstention,
        }

    def fiche_complete(etat: Etat) -> dict[str, Any]:
        """Les faits, sans rédaction : aucun appel au modèle, donc rien d'inventable."""
        identite = etat["fiche"]
        lignes = [f"{identite['nom']} — {identite['dossiers_visibles']} dossier(s) visible(s)"]
        lignes += ["", "Dossiers :"]
        lignes += [f"  {_ligne_dossier(dossier)}" for dossier in etat["dossiers"]]
        if etat["echanges"]:
            lignes += ["", "Derniers échanges :"]
            lignes += [f"  {_ligne_echange(echange)}" for echange in etat["echanges"]]
        points = etat["points"]
        lignes += ["", "Points d'attention :"]
        lignes += [f"  {point.ligne()}" for point in points] if points else ["  rien à signaler"]
        return {"reponse": "\n".join(lignes), "abstention": False}

    def synthese(etat: Etat) -> dict[str, Any]:
        """Le modèle rédige la prose ; les chiffres sont ajoutés tels quels par le code.

        Deux observations sur `qwen2.5:3b` ont conduit là. Il rattachait un délai au mauvais
        dossier tout en citant le bon nombre de jours : le chiffre passait la vérification
        alors que la phrase était fausse. Et il recopiait mal les montants à neuf chiffres
        (13 875 000 pour 13 750 000), ce qui faisait abstenir deux synthèses sur trois. On ne
        lui demande donc plus aucun chiffre : la prose situe, le code énonce.
        """
        invite = CONSIGNE_SYNTHESE.format(
            fiche=_en_texte(etat["fiche"]),
            dossiers="\n".join(_ligne_dossier(dossier) for dossier in etat["dossiers"]),
            echanges="\n".join(_ligne_echange(echange) for echange in etat["echanges"]),
            crm=_en_texte(elements_crm_du_client(session, etat["client_id"]))[:1500],
        )
        brut = str(modele_chat(Vitesse.RAPIDE, json=True).invoke(invite).content)
        texte = texte_attendu(lire_json(brut), "synthese")

        # La consigne interdit les chiffres ; s'il en glisse un, il doit venir des données.
        if not texte or avoue_ignorance(texte) or chiffres_douteux(texte, invite):
            logger.info("Synthèse écartée par les vérifications : %r", texte[:120])
            return {
                "reponse": "Je ne peux pas faire le point sur ce client à partir des données disponibles.",
                "abstention": True,
            }
        lignes = [texte, "", "Dossiers :"]
        lignes += [f"  {_ligne_dossier(dossier)}" for dossier in etat["dossiers"]]
        if etat["points"]:
            lignes += ["", "Points d'attention :"]
            lignes += [f"  {point.ligne()}" for point in etat["points"]]
        return {"reponse": "\n".join(lignes), "abstention": False}

    def journaliser(etat: Etat) -> dict[str, Any]:
        inscrire_au_journal(
            session,
            etat["utilisateur_id"],
            f"agent_client_{etat.get('intention', 'question')}",
            {
                "client_id": etat.get("client_id"),
                "demande": etat.get("demande", "")[:300],
                "abstention": etat.get("abstention", False),
                "dossiers_vus": len(etat.get("dossiers", [])),
                "points_attention": len(etat.get("points", [])),
            },
        )
        return {}

    def aiguiller(etat: Etat) -> str:
        if etat.get("abstention") and not etat.get("fiche"):
            return "journaliser"  # client invisible : on n'interroge rien
        return str(etat.get("intention", Intention.QUESTION))

    # Les surcharges de `add_node` n'acceptent pas un TypedDict `total=False` : seul le
    # constructeur du graphe échappe au contrôle, nos étapes restent typées.
    graphe: Any = StateGraph(Etat)
    graphe.add_node("comprendre", comprendre)
    graphe.add_node("collecter", collecter)
    graphe.add_node("question", questionner)
    graphe.add_node("synthese", synthese)
    graphe.add_node("fiche", fiche_complete)
    graphe.add_node("journaliser", journaliser)

    graphe.add_edge(START, "comprendre")
    graphe.add_edge("comprendre", "collecter")
    graphe.add_conditional_edges(
        "collecter",
        aiguiller,
        {
            "question": "question",
            "synthese": "synthese",
            "fiche": "fiche",
            "journaliser": "journaliser",
        },
    )
    for etape in ("question", "synthese", "fiche"):
        graphe.add_edge(etape, "journaliser")
    graphe.add_edge("journaliser", END)
    return graphe.compile()


def assister(session: Session, utilisateur_id: int, client_id: int, demande: str = "") -> ReponseAgent:
    """Point d'entrée de l'agent. La session porte les droits de l'utilisateur."""
    depart = time.perf_counter()
    etat_final = construire_graphe(session).invoke(
        Etat(utilisateur_id=utilisateur_id, client_id=client_id, demande=demande)
    )
    return ReponseAgent(
        intention=str(etat_final.get("intention", "")),
        texte=str(etat_final.get("reponse", "")),
        citations=list(etat_final.get("citations", [])),
        donnees={
            "fiche": etat_final.get("fiche", {}),
            "dossiers": list(etat_final.get("dossiers", [])),
            "echanges": list(etat_final.get("echanges", [])),
            "points_attention": [asdict(point) for point in etat_final.get("points", [])],
        },
        abstention=bool(etat_final.get("abstention", False)),
        secondes=time.perf_counter() - depart,
    )
