"""Agent de tri du courrier entrant (F9).

Pour chaque email qui n'est rattaché à aucun dossier, il propose : à quel dossier le
rattacher, avec quelle urgence le traiter, un résumé, et un brouillon de réponse. Pour un
expéditeur qui n'a pas de dossier — un prospect qui demande un rendez-vous — il propose une
tâche de rappel dans le CRM.

**Il ne fait rien.** Il dépose des propositions ; un humain les valide ou les rejette, et
c'est la validation qui produit l'effet (`agents/propositions.py`).

Le partage du travail suit l'ADR 0005, poussé un cran plus loin : le **rattachement et la
priorité sont calculés par des règles** (`agents/indices.py`), parce qu'un email mal rattaché
va dans le dossier d'un autre client — c'est une fuite, pas une imprécision. Le modèle ne
fait que ce qu'il sait faire : résumer et rédiger.

    lire ──► resumer ──► rediger ──► proposer ──► journaliser ──► fin
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.agents.commun import (
    ReponseAgent,
    chiffres_douteux,
    inscrire_au_journal,
    lire_json,
    texte_attendu,
)
from jurismind.agents.indices import (
    Candidat,
    Priorite,
    candidats,
    echeance_relance,
    priorite,
    retenir,
    societe_de,
    texte_de,
)
from jurismind.agents.propositions import (
    Decision,
    deja_proposee,
    enregistrer,
    tache_pour_prospect,
)
from jurismind.db.models import (
    Communication,
    Confiance,
    Contact,
    Partie,
    TypeProposition,
)
from jurismind.llm import Vitesse, modele_chat
from jurismind.rag.verification import avoue_ignorance

logger = logging.getLogger(__name__)

CARACTERES_MAX = 3000

CONSIGNE_RESUME = """Tu résumes un email reçu par un cabinet d'avocats sénégalais.

De : {expediteur}
Objet : {objet}

{corps}

Résume en 2 phrases au maximum : ce que l'expéditeur annonce ou demande, et ce qu'il attend
du cabinet. Ne reprends que ce qui est écrit. N'ajoute aucun montant ni aucune date qui n'y
figure pas.

Réponds uniquement par ce JSON : {{"resume": "…"}}
"""

CONSIGNE_BROUILLON = """Tu rédiges le corps d'un **brouillon** d'accusé de réception pour un
cabinet d'avocats sénégalais.

Le cabinet **vient de recevoir** le message ci-dessous. Tu écris la réponse du cabinet à
son expéditeur : c'est donc lui qui a écrit, et le cabinet qui répond.

De : {expediteur}
Objet : {objet}

{corps}

Rédige 2 phrases au maximum : dire que son message est bien reçu, et annoncer la suite
({suite}).
Règles absolues :
- n'écris **ni formule d'appel ni formule de politesse** : elles sont ajoutées à part ;
- ne prends aucun engagement sur le fond, ne donne aucun avis juridique, ne reconnais rien ;
- n'annonce ni montant, ni date, ni délai.

Réponds uniquement par ce JSON : {{"brouillon": "…"}}
"""

# Ce qu'on peut annoncer, selon qui écrit.
SUITES = {
    "confrère": "que le dossier est en cours d'examen et qu'une réponse suivra",
    "client": "que le cabinet revient vers lui après examen des pièces",
    "prospect": "qu'un rendez-vous lui sera proposé",
    "inconnu": "que le message est transmis à l'avocat concerné",
}
# Les formules sont écrites par le code : le modèle, à qui l'on donnait la qualité de
# l'expéditeur, s'en servait comme d'un titre et saluait « Cher prospect ».
APPELS = {
    "confrère": "Mon cher confrère,",
    "client": "Madame, Monsieur,",
    "prospect": "Madame, Monsieur,",
    "inconnu": "Madame, Monsieur,",
}
POLITESSES = {
    "confrère": "Bien confraternellement,",
    "client": "Je vous prie d'agréer l'expression de mes salutations distinguées.",
    "prospect": "Je vous prie d'agréer l'expression de mes salutations distinguées.",
    "inconnu": "Je vous prie d'agréer l'expression de mes salutations distinguées.",
}


def mettre_en_lettre(corps: str, qualite: str) -> str:
    """Assemble le brouillon : appel, corps rédigé, politesse. Vide si le corps est vide.

    L'appel ne nomme pas l'interlocuteur. Nommer quelqu'un en français suppose une
    civilité, et la table `contacts` n'en porte pas : la déduire du prénom, c'est se
    tromper une fois sur deux — « Monsieur Diallo » pour Ndeye Diallo. Tant que le
    cabinet ne saisit pas la civilité, la formule neutre est la seule juste.
    """
    if not corps.strip():
        return ""
    appel = APPELS.get(qualite, APPELS["inconnu"])
    politesse = POLITESSES.get(qualite, POLITESSES["inconnu"])
    return f"{appel}{chr(10)}{chr(10)}{corps.strip()}{chr(10)}{chr(10)}{politesse}"


@dataclass
class Tri:
    """Ce que l'agent a conclu pour un email, avant toute validation."""

    communication_id: int
    expediteur: str
    objet: str
    priorite: str
    priorite_pourquoi: str
    qualite: str
    dossier: str | None
    rattachement_pourquoi: str
    resume: str
    brouillon: str
    propositions: list[int]

    def lignes(self) -> list[str]:
        ou = f"→ {self.dossier} ({self.rattachement_pourquoi})" if self.dossier else "→ aucun dossier"
        return [
            f"[{self.priorite}] {self.objet or 'sans objet'} — de {self.expediteur} ({self.qualite})",
            f"   {ou}",
            f"   priorité : {self.priorite_pourquoi}",
            f"   résumé   : {self.resume or '(écarté par les vérifications)'}",
            f"   propositions déposées : {self.propositions or 'aucune'}",
        ]


class Etat(TypedDict, total=False):
    """Ce que le graphe se transmet d'une étape à l'autre, pour un email."""

    utilisateur_id: int
    communication_id: int
    echange: Any  # l'objet Communication, chargé une seule fois
    candidat: Candidat | None
    priorite: str
    priorite_pourquoi: str
    qualite: str
    client_id: int | None
    resume: str
    brouillon: str
    propositions: list[int]


def tronquer(texte: str) -> str:
    return texte if len(texte) <= CARACTERES_MAX else texte[:CARACTERES_MAX] + "\n[…]"


def qualite_de(session: Session, echange: Communication, candidat: Candidat | None) -> tuple[str, int | None]:
    """Qui écrit : un confrère, un client, un prospect ?

    Déduit de la base — une partie au dossier, un contact du client — et pas du ton du
    message. Rend aussi l'identifiant du client, quand l'expéditeur est l'un de ses contacts.
    """
    email = (echange.expediteur or "").lower()
    if email:
        partie = session.scalars(select(Partie).where(Partie.email.ilike(email))).first()
        if partie is not None:
            return "confrère", None
        contact = session.scalars(select(Contact).where(Contact.email.ilike(email))).first()
        if contact is not None:
            return "client", contact.client_id
    if candidat is not None:
        return "client", None
    return ("prospect" if societe_de(echange.expediteur) else "inconnu"), None


def construire_graphe(session: Session) -> Any:
    """Construit le graphe de l'agent pour une session donnée (donc pour un utilisateur donné)."""

    def lire(etat: Etat) -> dict[str, Any]:
        echange = session.get(Communication, etat["communication_id"])
        if echange is None:
            return {"echange": None}
        candidat = retenir(candidats(session, echange))
        niveau, pourquoi = priorite(session, echange, candidat)
        qualite, client_id = qualite_de(session, echange, candidat)
        return {
            "echange": echange,
            "candidat": candidat,
            "priorite": str(niveau),
            "priorite_pourquoi": pourquoi,
            "qualite": qualite,
            "client_id": client_id,
        }

    def resumer(etat: Etat) -> dict[str, Any]:
        echange = etat["echange"]
        corps = tronquer(echange.corps or "")
        invite = CONSIGNE_RESUME.format(
            expediteur=echange.expediteur or "inconnu",
            objet=echange.objet or "sans objet",
            corps=corps,
        )
        brut = str(modele_chat(Vitesse.RAPIDE, json=True).invoke(invite).content)
        resume = texte_attendu(lire_json(brut), "resume")
        if resume and (avoue_ignorance(resume) or chiffres_douteux(resume, texte_de(echange))):
            logger.info("Résumé écarté par les vérifications : %r", resume[:100])
            resume = ""
        return {"resume": resume}

    def rediger(etat: Etat) -> dict[str, Any]:
        echange = etat["echange"]
        qualite = etat["qualite"]
        invite = CONSIGNE_BROUILLON.format(
            expediteur=echange.expediteur or "inconnu",
            objet=echange.objet or "sans objet",
            corps=tronquer(echange.corps or ""),
            suite=SUITES.get(qualite, SUITES["inconnu"]),
        )
        brut = str(modele_chat(Vitesse.RAPIDE, json=True).invoke(invite).content)
        corps = texte_attendu(lire_json(brut), "brouillon")
        # Un accusé de réception n'a aucune raison d'annoncer un chiffre : s'il en contient
        # un, il sort du cadre qu'on lui a fixé et on ne le propose pas.
        if corps and chiffres_douteux(corps, texte_de(echange)):
            logger.info("Brouillon écarté, chiffre non fondé : %r", corps[:100])
            corps = ""
        return {"brouillon": mettre_en_lettre(corps, qualite)}

    def proposer(etat: Etat) -> dict[str, Any]:
        echange = etat["echange"]
        candidat = etat.get("candidat")
        deposees: list[int] = []
        commun = {
            "communication_id": echange.id,
            "client_id": etat.get("client_id"),
            "donnees": {
                "priorite": etat["priorite"],
                "priorite_pourquoi": etat["priorite_pourquoi"],
                "qualite_expediteur": etat["qualite"],
                "resume": etat.get("resume", ""),
            },
        }

        if candidat is not None and not deja_proposee(session, echange.id, TypeProposition.RATTACHEMENT):
            deposees.append(
                enregistrer(
                    session,
                    TypeProposition.RATTACHEMENT,
                    titre=f"Rattacher « {echange.objet or 'sans objet'} » au dossier {candidat.reference}",
                    justification=candidat.justification(),
                    confiance=candidat.confiance,
                    dossier_id=candidat.dossier_id,
                    **commun,
                ).id
            )

        if etat.get("brouillon") and not deja_proposee(session, echange.id, TypeProposition.BROUILLON):
            deposees.append(
                enregistrer(
                    session,
                    TypeProposition.BROUILLON,
                    titre=f"Réponse à « {echange.objet or 'sans objet'} »",
                    justification=f"accusé de réception à un {etat['qualite']}, à relire avant envoi",
                    confiance=Confiance.MOYENNE,
                    dossier_id=candidat.dossier_id if candidat else None,
                    contenu=etat["brouillon"],
                    **commun,
                ).id
            )

        # Personne à rattacher : la suite utile n'est pas juridique, elle est commerciale.
        if candidat is None and not deja_proposee(session, echange.id, TypeProposition.TACHE_CRM):
            societe = societe_de(echange.expediteur)
            if societe:
                echeance = echeance_relance(datetime.now(UTC).date())
                deposees.append(
                    enregistrer(
                        session,
                        TypeProposition.TACHE_CRM,
                        titre=f"Rappeler {societe} — {echange.objet or 'demande entrante'}",
                        justification="aucun dossier ne correspond : expéditeur à qualifier",
                        confiance=Confiance.MOYENNE,
                        contenu=etat.get("resume") or None,
                        **{
                            **commun,
                            "donnees": {
                                **commun["donnees"],
                                **tache_pour_prospect(
                                    echange, etat.get("resume", ""), echeance.isoformat(), societe
                                ),
                            },
                        },
                    ).id
                )
        return {"propositions": deposees}

    def journaliser(etat: Etat) -> dict[str, Any]:
        echange = etat["echange"]
        candidat = etat.get("candidat")
        inscrire_au_journal(
            session,
            etat["utilisateur_id"],
            "agent_tri_courrier",
            {
                "communication_id": echange.id if echange else None,
                "priorite": etat.get("priorite"),
                "dossier_propose": candidat.reference if candidat else None,
                "propositions": etat.get("propositions", []),
            },
            dossier_id=candidat.dossier_id if candidat else None,
        )
        return {}

    # Les surcharges de `add_node` n'acceptent pas un TypedDict `total=False` : seul le
    # constructeur du graphe échappe au contrôle, nos étapes restent typées.
    graphe: Any = StateGraph(Etat)
    graphe.add_node("lire", lire)
    graphe.add_node("resumer", resumer)
    graphe.add_node("rediger", rediger)
    graphe.add_node("proposer", proposer)
    graphe.add_node("journaliser", journaliser)

    graphe.add_edge(START, "lire")
    graphe.add_edge("lire", "resumer")
    graphe.add_edge("resumer", "rediger")
    graphe.add_edge("rediger", "proposer")
    graphe.add_edge("proposer", "journaliser")
    graphe.add_edge("journaliser", END)
    return graphe.compile()


def trier_un(session: Session, utilisateur_id: int, communication_id: int) -> Tri | None:
    """Trie un email. `None` si l'utilisateur ne peut pas le voir."""
    etat = construire_graphe(session).invoke(
        Etat(utilisateur_id=utilisateur_id, communication_id=communication_id)
    )
    echange = etat.get("echange")
    if echange is None:
        return None
    candidat = etat.get("candidat")
    return Tri(
        communication_id=echange.id,
        expediteur=echange.expediteur or "inconnu",
        objet=echange.objet or "",
        priorite=str(etat.get("priorite", Priorite.BASSE)),
        priorite_pourquoi=str(etat.get("priorite_pourquoi", "")),
        qualite=str(etat.get("qualite", "inconnu")),
        dossier=candidat.reference if candidat else None,
        rattachement_pourquoi=candidat.justification() if candidat else "aucun indice suffisant",
        resume=str(etat.get("resume", "")),
        brouillon=str(etat.get("brouillon", "")),
        propositions=list(etat.get("propositions", [])),
    )


def courrier_a_trier(session: Session, limite: int = 20) -> list[Communication]:
    """Les échanges qu'aucun dossier ne réclame, du plus ancien au plus récent."""
    return list(
        session.scalars(
            select(Communication)
            .where(Communication.dossier_id.is_(None))
            .order_by(Communication.date_echange)
            .limit(limite)
        ).all()
    )


def trier(session: Session, utilisateur_id: int, limite: int = 20) -> ReponseAgent:
    """Trie tout le courrier en attente et rend le compte rendu de ce qui a été proposé."""
    depart = time.perf_counter()
    tris = [
        tri
        for echange in courrier_a_trier(session, limite)
        if (tri := trier_un(session, utilisateur_id, echange.id)) is not None
    ]
    # Les urgences d'abord, dans le texte **comme** dans les données rendues à l'API.
    tris.sort(key=lambda tri: ("haute", "moyenne", "basse").index(tri.priorite))
    lignes: list[str] = []
    for tri in tris:
        lignes += tri.lignes() + [""]
    deposees = sum(len(tri.propositions) for tri in tris)
    lignes.append(f"{len(tris)} email(s) trié(s), {deposees} proposition(s) en attente de décision.")
    return ReponseAgent(
        intention="tri_courrier",
        texte="\n".join(lignes),
        donnees={"tris": [vars(tri) for tri in tris], "propositions_deposees": deposees},
        abstention=not tris,
        secondes=time.perf_counter() - depart,
    )


def resume_des_propositions(propositions: list[Decision]) -> str:
    """Met en forme ce qui attend une décision, pour la ligne de commande et pour l'API."""
    if not propositions:
        return "Rien n'attend de décision."
    lignes = [f"{len(propositions)} proposition(s) en attente :", ""]
    for proposition in propositions:
        lignes.append(f"  #{proposition.id} [{proposition.confiance}] {proposition.type}")
        lignes.append(f"      {proposition.titre}")
        lignes.append(f"      fondement : {proposition.justification}")
        if proposition.contenu:
            extrait = proposition.contenu.replace("\n", " ")[:160]
            lignes.append(f"      contenu   : {extrait}…")
        lignes.append("")
    return "\n".join(lignes)
