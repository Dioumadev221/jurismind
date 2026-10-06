"""Agent d'analyse d'un document (F8).

Il fait sur une pièce ce qu'un collaborateur ferait en la découvrant : reconnaître de quel
acte il s'agit, en dire l'essentiel, relever ce qui engage, et rappeler les valeurs déjà
tirées de l'acte (F5). Il répond aussi à une question portant sur cette seule pièce.

Trois garanties, dans l'esprit de l'ADR 0005 :

- la **catégorie** retenue appartient obligatoirement à la liste des types connus du cabinet,
  sinon elle est écartée : le modèle ne crée pas de nouveau vocabulaire ;
- un **point clé** n'est affiché que si sa citation se retrouve dans le document
  (`citation_verifiee`, ADR 0003) — c'est ce qui distingue un relevé d'une paraphrase ;
- le **résumé** ne peut avancer un chiffre absent du document.

    charger ──┬─► question ─────────────────────────────┐
              └─► classer ──► resumer ──► points_cles ──┴─► journaliser ──► fin
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from jurismind.agents.commun import (
    ReponseAgent,
    chiffres_douteux,
    inscrire_au_journal,
    lire_json,
    liste_attendue,
    texte_attendu,
)
from jurismind.agents.outils import extraction_du_document, fiche_document
from jurismind.db.models import Document
from jurismind.llm import Vitesse, modele_chat
from jurismind.rag import repondre
from jurismind.rag.verification import avoue_ignorance, citation_verifiee
from jurismind.retrieval import Filtres

logger = logging.getLogger(__name__)

# Au-delà, le début et la fin d'un acte suffisent : en-tête, parties, montants, dispositif.
CARACTERES_MAX = 6000
# Pour reconnaître la nature d'un acte, son en-tête suffit : il s'annonce dans ses
# premières lignes (« MISE EN DEMEURE », « PROCÈS-VERBAL DE SIGNIFICATION »,
# « FACTURE N° … »). Lui donner l'acte entier allonge le classement sans rien apporter.
CARACTERES_CLASSEMENT = 1500
POINTS_MAX = 5

# Les types d'actes que le cabinet manipule, avec de quoi les reconnaître. La catégorie
# retenue ici alimente `categorie_detectee`, donc le choix du schéma d'extraction (ADR 0004).
CATEGORIES = {
    "FACTURE": "facture ou note d'honoraires, avec un montant à payer",
    "BON_LIVRAISON": "bon de livraison ou de réception de marchandises",
    "ETAT_LOYERS": "décompte de loyers ou de charges dus",
    "MISE_EN_DEMEURE": "lettre sommant quelqu'un de payer ou d'exécuter, avec un délai",
    "COMMANDEMENT": "commandement de payer délivré par un huissier",
    "REQUETE_IP": "requête adressée au président du tribunal aux fins d'injonction de payer",
    "ORDONNANCE_IP": "ordonnance d'injonction de payer rendue par un juge",
    "ORDONNANCE_EXECUTOIRE": "ordonnance revêtue de la formule exécutoire",
    "ORDONNANCE_REFERE": "ordonnance de référé rendue en urgence",
    "OPPOSITION": "acte par lequel un débiteur s'oppose à une injonction de payer",
    "ASSIGNATION": "acte citant une partie à comparaître devant le tribunal",
    "ASSIGNATION_REFERE": "assignation à une audience de référé",
    "CONCLUSIONS": "écritures développant les prétentions d'une partie",
    "CONCLUSIONS_ADV": "écritures de la partie adverse",
    "JUGEMENT": "décision rendue par un tribunal, avec un dispositif",
    "PV_SIGNIFICATION": "procès-verbal par lequel un huissier remet un acte",
    "PV_SAISIE": "procès-verbal de saisie dressé par un huissier",
    "CONTRAT": "contrat signé entre deux parties",
    "PROJET_CONTRAT": "projet de contrat, non signé",
    "BAIL": "bail commercial ou d'habitation",
    "PROTOCOLE": "protocole d'accord ou transaction mettant fin à un litige",
    "STATUTS": "statuts d'une société",
    "PROJET_STATUTS": "projet de statuts, non signé",
    "ATTESTATION_RCCM": "attestation d'immatriculation au registre du commerce",
    "ACTE_CESSION": "acte de cession de parts, de fonds ou de créance",
    "NOTE": "note interne au cabinet",
    "OBSERVATIONS": "observations adressées à une juridiction",
    "DIVERS": "aucun des types ci-dessus",
}

CONSIGNE_CLASSEMENT = """Tu reconnais la nature d'un acte juridique sénégalais (droit OHADA).

Types possibles, et comment les reconnaître :
{types}

Document (« {titre} ») :
{texte}

Choisis le type qui correspond. Si aucun ne convient, réponds "DIVERS".
Réponds uniquement par ce JSON : {{"type": "UN_DES_TYPES_CI_DESSUS"}}
"""

CONSIGNE_RESUME = """Tu résumes un acte juridique pour l'avocat qui le reçoit.

Type de l'acte : {categorie}

Document (« {titre} ») :
{texte}

Résume en 3 phrases au maximum : de quoi il s'agit, qui est concerné, ce que l'acte produit.
Ne reprends que ce qui est écrit dans le document. N'ajoute aucun montant ni aucune date qui
n'y figure pas.

Réponds uniquement par ce JSON : {{"resume": "…"}}
"""

CONSIGNE_POINTS = """Tu relèves ce qui engage dans un acte juridique, pour l'avocat qui le reçoit.

Type de l'acte : {categorie}

Document (« {titre} ») :
{texte}

Relève au maximum {maximum} points : délai, montant, pénalité, clause de juridiction ou
d'arbitrage, reconduction, résiliation, garantie, condition suspensive, obligation datée.
Ne mentionne que les points réellement présents dans ce document.
Pour chacun, recopie **mot pour mot** la phrase du document qui le porte : une phrase que tu
reformules sera écartée. Si une nature de point ne figure pas dans le document, ne l'inscris
pas du tout plutôt que de mettre une citation vide.

Réponds uniquement par ce JSON :
{{"points": [{{"titre": "en trois mots", "citation": "la phrase recopiée du document"}}]}}
"""


class Intention(StrEnum):
    ANALYSE = "analyse"
    QUESTION = "question"


@dataclass
class PointCle:
    """Un élément qui engage, et la phrase du document qui le porte."""

    titre: str
    citation: str

    def ligne(self) -> str:
        return f"{self.titre} — « {self.citation} »"


class Etat(TypedDict, total=False):
    """Ce que le graphe se transmet d'une étape à l'autre."""

    utilisateur_id: int
    document_id: int
    demande: str
    intention: str
    fiche: dict[str, Any]
    categorie: str
    desaccord: bool
    resume: str
    points: list[PointCle]
    extraction: dict[str, Any] | None
    reponse: str
    citations: list[dict[str, Any]]
    abstention: bool


def entete(texte: str) -> str:
    """Les premières lignes de l'acte : ce qui suffit à reconnaître sa nature."""
    return texte[:CARACTERES_CLASSEMENT]


def texte_utile(texte: str) -> str:
    """Début et fin de l'acte : au-delà, le modèle ralentit sans rien gagner."""
    if len(texte) <= CARACTERES_MAX:
        return texte
    moitie = CARACTERES_MAX // 2
    return texte[:moitie] + "\n[…]\n" + texte[-moitie:]


def categorie_valide(valeur: str) -> str | None:
    """La catégorie doit appartenir à la liste connue du cabinet, sinon elle est écartée."""
    propre = valeur.strip().upper().replace(" ", "_").replace("-", "_")
    return propre if propre in CATEGORIES else None


def points_verifies(proposes: list[Any], document: str) -> list[PointCle]:
    """Ne garde que les points dont la citation se retrouve dans le document.

    Une citation **vide** n'est pas un rejet : le modèle énumère volontiers les natures de
    points qu'on lui a listées en mettant `null` sur celles qu'il ne trouve pas. C'est lui
    qui dit « absent », et il a raison de le dire. Seule une citation *affirmée* mais
    introuvable est un rejet — c'est cela qu'on mesure.
    """
    retenus: list[PointCle] = []
    for propose in proposes:
        if not isinstance(propose, dict):
            continue
        valeur = propose.get("citation")
        citation = str(valeur).strip() if isinstance(valeur, str) else ""
        if not citation:
            continue
        if not citation_verifiee(citation, document):
            logger.info("Point écarté, citation introuvable dans le document : %r", citation[:80])
            continue
        if any(retenu.citation == citation for retenu in retenus):
            continue
        titre = str(propose.get("titre", "")).strip() or "Point relevé"
        retenus.append(PointCle(titre=titre, citation=citation))
    return retenus[:POINTS_MAX]


def citations_affirmees(proposes: list[Any]) -> int:
    """Nombre de points où le modèle a réellement avancé une citation (dénominateur de la mesure)."""
    return sum(
        1
        for propose in proposes
        if isinstance(propose, dict) and isinstance(propose.get("citation"), str)
        if str(propose["citation"]).strip()
    )


def construire_graphe(session: Session) -> Any:
    """Construit le graphe de l'agent pour une session donnée (donc pour un utilisateur donné)."""

    def charger(etat: Etat) -> dict[str, Any]:
        fiche = fiche_document(session, etat["document_id"])
        if fiche is None:
            # Pièce d'un dossier qui n'est pas ouvert à cet utilisateur : on s'arrête là.
            return {"fiche": {}, "abstention": True, "reponse": "Document introuvable."}
        if not fiche["texte"]:
            return {
                "fiche": fiche,
                "abstention": True,
                "reponse": "Ce document n'a pas encore été lu : lancer l'ingestion.",
            }
        intention = Intention.QUESTION if etat.get("demande", "").strip() else Intention.ANALYSE
        logger.info("Intention retenue : %s", intention)
        return {
            "fiche": fiche,
            "intention": str(intention),
            "extraction": extraction_du_document(session, etat["document_id"]),
        }

    def questionner(etat: Etat) -> dict[str, Any]:
        """La recherche est bornée au dossier de la pièce ; la réponse cite ses extraits."""
        reponse = repondre(
            session,
            etat["demande"],
            filtres=Filtres(dossier_id=etat["fiche"]["dossier_id"]),
        )
        return {
            "reponse": reponse.texte,
            "citations": [asdict(citation) for citation in reponse.citations],
            "abstention": reponse.abstention,
        }

    def classer(etat: Etat) -> dict[str, Any]:
        """Détermine le type de l'acte et l'inscrit en base (`categorie_detectee`)."""
        fiche = etat["fiche"]
        invite = CONSIGNE_CLASSEMENT.format(
            types="\n".join(f"- {code} : {quoi}" for code, quoi in CATEGORIES.items()),
            titre=fiche["titre"],
            texte=entete(fiche["texte"]),
        )
        brut = str(modele_chat(Vitesse.RAPIDE, json=True).invoke(invite).content)
        categorie = categorie_valide(texte_attendu(lire_json(brut), "type"))
        if categorie is None:
            logger.info("Classement écarté : %r", brut[:120])
            return {"categorie": "", "desaccord": False}

        document = session.get(Document, etat["document_id"])
        if document is not None:
            document.categorie_detectee = categorie
            session.flush()
        source = (fiche["categorie_source"] or "").upper()
        return {"categorie": categorie, "desaccord": bool(source) and source != categorie}

    def resumer(etat: Etat) -> dict[str, Any]:
        fiche = etat["fiche"]
        invite = CONSIGNE_RESUME.format(
            categorie=etat.get("categorie") or fiche["categorie_source"] or "inconnu",
            titre=fiche["titre"],
            texte=entete(fiche["texte"]),
        )
        brut = str(modele_chat(Vitesse.RAPIDE, json=True).invoke(invite).content)
        resume = texte_attendu(lire_json(brut), "resume")
        # Un chiffre qui n'est pas dans le document ne peut pas venir du document.
        if resume and (avoue_ignorance(resume) or chiffres_douteux(resume, fiche["texte"])):
            logger.info("Résumé écarté par les vérifications : %r", resume[:120])
            resume = ""
        return {"resume": resume}

    def points_cles(etat: Etat) -> dict[str, Any]:
        fiche = etat["fiche"]
        invite = CONSIGNE_POINTS.format(
            categorie=etat.get("categorie") or fiche["categorie_source"] or "inconnu",
            titre=fiche["titre"],
            texte=texte_utile(fiche["texte"]),
            maximum=POINTS_MAX,
        )
        brut = str(modele_chat(Vitesse.RAPIDE, json=True).invoke(invite).content)
        proposes = liste_attendue(lire_json(brut), "points")
        points = points_verifies(proposes, fiche["texte"])
        logger.info(
            "Points retenus : %d sur %d citations affirmées (%d natures explorées)",
            len(points),
            citations_affirmees(proposes),
            len(proposes),
        )
        return {"points": points, "reponse": _rendu(etat, points)}

    def journaliser(etat: Etat) -> dict[str, Any]:
        inscrire_au_journal(
            session,
            etat["utilisateur_id"],
            f"agent_document_{etat.get('intention', 'analyse')}",
            {
                "document_id": etat.get("document_id"),
                "demande": etat.get("demande", "")[:300],
                "abstention": etat.get("abstention", False),
                "categorie_detectee": etat.get("categorie", ""),
                "desaccord_categorie": etat.get("desaccord", False),
                "points_retenus": len(etat.get("points", [])),
            },
            dossier_id=etat.get("fiche", {}).get("dossier_id"),
        )
        return {}

    def aiguiller(etat: Etat) -> str:
        if etat.get("abstention"):
            return "journaliser"  # document invisible ou non lu : on n'interroge rien
        return str(etat.get("intention", Intention.ANALYSE))

    # Les surcharges de `add_node` n'acceptent pas un TypedDict `total=False` : seul le
    # constructeur du graphe échappe au contrôle, nos étapes restent typées.
    graphe: Any = StateGraph(Etat)
    graphe.add_node("charger", charger)
    graphe.add_node("question", questionner)
    graphe.add_node("classer", classer)
    graphe.add_node("resumer", resumer)
    graphe.add_node("points_cles", points_cles)
    graphe.add_node("journaliser", journaliser)

    graphe.add_edge(START, "charger")
    graphe.add_conditional_edges(
        "charger",
        aiguiller,
        {"analyse": "classer", "question": "question", "journaliser": "journaliser"},
    )
    graphe.add_edge("classer", "resumer")
    graphe.add_edge("resumer", "points_cles")
    graphe.add_edge("points_cles", "journaliser")
    graphe.add_edge("question", "journaliser")
    graphe.add_edge("journaliser", END)
    return graphe.compile()


def _rendu(etat: Etat, points: list[PointCle]) -> str:
    """Met l'analyse en forme. Ce que le code sait, le code l'écrit."""
    fiche = etat["fiche"]
    categorie = etat.get("categorie") or "non déterminé"
    lecture = " (lu par OCR)" if fiche["lu_par_ocr"] else ""
    lignes = [f"{fiche['titre']}{lecture}", f"Type reconnu : {categorie}"]
    if etat.get("desaccord"):
        lignes.append(f"  Le cabinet avait saisi : {fiche['categorie_source']} — à vérifier.")
    if etat.get("resume"):
        lignes += ["", etat["resume"]]
    lignes += ["", "Ce qui engage :"]
    lignes += [f"  - {point.ligne()}" for point in points] if points else ["  rien de relevé"]
    extraction = etat.get("extraction")
    if extraction:
        valeurs = ", ".join(f"{cle} = {valeur}" for cle, valeur in extraction["donnees"].items())
        lignes += ["", f"Valeurs extraites ({extraction['schema']}, {extraction['statut']}) : {valeurs}"]
        if extraction["champs_douteux"]:
            lignes.append(f"  À relire : {', '.join(extraction['champs_douteux'])}")
    return "\n".join(lignes)


def assister(session: Session, utilisateur_id: int, document_id: int, demande: str = "") -> ReponseAgent:
    """Point d'entrée de l'agent. La session porte les droits de l'utilisateur."""
    depart = time.perf_counter()
    etat_final = construire_graphe(session).invoke(
        Etat(utilisateur_id=utilisateur_id, document_id=document_id, demande=demande)
    )
    fiche = dict(etat_final.get("fiche", {}))
    fiche.pop("texte", None)  # le texte complet n'a pas à remonter dans la réponse
    return ReponseAgent(
        intention=str(etat_final.get("intention", "")),
        texte=str(etat_final.get("reponse", "")),
        citations=list(etat_final.get("citations", [])),
        donnees={
            "document": fiche,
            "categorie_detectee": etat_final.get("categorie", ""),
            "desaccord_categorie": bool(etat_final.get("desaccord", False)),
            "resume": str(etat_final.get("resume", "")),
            "points_cles": [asdict(point) for point in etat_final.get("points", [])],
            "extraction": etat_final.get("extraction"),
        },
        abstention=bool(etat_final.get("abstention", False)),
        secondes=time.perf_counter() - depart,
    )
