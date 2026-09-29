"""Répondre à une question à partir des seules pièces du cabinet, avec citations.

Trois garde-fous contre les réponses inventées :

1. **Le modèle ne reçoit que les extraits retrouvés.** Il ne répond jamais de mémoire.
2. **Les citations sont vérifiées par le code**, pas par le modèle : une citation qui
   désigne une source absente est retirée, et une réponse sans aucune citation valide est
   refusée.
3. **L'abstention est un résultat acceptable.** Si rien n'est retrouvé, ou si le modèle ne
   sait pas, JurisMind le dit — un avocat préfère « je ne trouve pas » à une invention.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from jurismind.llm import Vitesse, modele_chat
from jurismind.rag.verification import (
    avoue_ignorance,
    chiffres_ancres,
    citation_verifiee,
    references_respectees,
)
from jurismind.retrieval import Filtres, Resultat, rechercher

logger = logging.getLogger(__name__)

EXTRAITS_FOURNIS = 5
PHRASE_ABSTENTION = "Je ne trouve pas cette information dans les pièces du dossier."

# Consigne volontairement courte et à un seul critère : un modèle de 3 milliards de
# paramètres se trompe dès qu'on lui demande plusieurs jugements à la fois.
CONSIGNE = """Tu es l'assistant documentaire d'un cabinet d'avocats sénégalais.

Sources :
{sources}

Question : {question}

Réponds uniquement par un objet JSON de cette forme :
{{"reponse": "ta réponse en français, 4 phrases au maximum",
  "sources": [1],
  "citation": "la phrase exacte de la source qui justifie ta réponse, recopiée mot pour mot"}}

Règles :
- Utilise UNIQUEMENT les sources ci-dessus, jamais tes connaissances générales.
- "sources" contient les numéros des sources utilisées : au moins un numéro.
- "citation" doit être recopiée telle quelle depuis une source citée.
- Si aucune source ne répond à la question, renvoie : {{"reponse": "", "sources": [], "citation": ""}}
"""


@dataclass
class Citation:
    """Une source réellement utilisée par la réponse."""

    numero: int
    reference: str
    extrait_id: int
    dossier_id: int | None
    similarite: float | None = None


@dataclass
class Reponse:
    texte: str
    citations: list[Citation] = field(default_factory=list)
    abstention: bool = False
    secondes: float = 0.0
    sources_examinees: int = 0
    # Extraits fournis au modèle : utiles pour l'audit et pour mesurer la recherche.
    extraits_examines: list[int] = field(default_factory=list)

    @property
    def fiable(self) -> bool:
        """Une réponse affirmative sans citation n'est jamais présentée à l'utilisateur."""
        return self.abstention or bool(self.citations)


def construire_sources(resultats: list[Resultat]) -> str:
    return "\n\n".join(
        f"[{numero}] {resultat.reference}\n{resultat.extrait.contenu}"
        for numero, resultat in enumerate(resultats, start=1)
    )


def _lire_json(brut: str) -> dict[str, object] | None:
    """Le modèle renvoie du JSON ; on reste tolérant s'il l'entoure de texte."""
    try:
        return dict(json.loads(brut))
    except (ValueError, TypeError):
        debut, fin = brut.find("{"), brut.rfind("}")
        if debut == -1 or fin <= debut:
            return None
        try:
            return dict(json.loads(brut[debut : fin + 1]))
        except (ValueError, TypeError):
            return None


def _citations_valides(numeros: object, resultats: list[Resultat]) -> list[Citation]:
    """Ne garde que les numéros qui désignent une source réellement fournie."""
    citations: list[Citation] = []
    for valeur in numeros if isinstance(numeros, list) else []:
        try:
            numero = int(valeur)
        except (TypeError, ValueError):
            continue
        if not 1 <= numero <= len(resultats) or any(c.numero == numero for c in citations):
            logger.warning("Citation écartée : %r", valeur)
            continue
        resultat = resultats[numero - 1]
        citations.append(
            Citation(
                numero=numero,
                reference=resultat.reference,
                extrait_id=resultat.extrait.id,
                dossier_id=resultat.extrait.dossier_id,
                similarite=resultat.similarite,
            )
        )
    return citations


def repondre(
    session: Session,
    question: str,
    filtres: Filtres | None = None,
    extraits: int = EXTRAITS_FOURNIS,
    vitesse: Vitesse = Vitesse.RAPIDE,
) -> Reponse:
    """Cherche, fait rédiger, puis vérifie. La session porte les droits de l'utilisateur."""
    depart = time.perf_counter()
    resultats = rechercher(session, question, filtres=filtres, limite=extraits)

    if not resultats:
        # Rien à lire : inutile de déranger le modèle, qui inventerait peut-être.
        return Reponse(texte=PHRASE_ABSTENTION, abstention=True, secondes=time.perf_counter() - depart)

    invite = CONSIGNE.format(sources=construire_sources(resultats), question=question.strip())
    brut = str(modele_chat(vitesse, json=True).invoke(invite).content).strip()
    donnees = _lire_json(brut)

    if donnees is None:
        logger.warning("Réponse illisible du modèle : %r", brut[:160])
        return Reponse(
            texte=PHRASE_ABSTENTION,
            abstention=True,
            secondes=time.perf_counter() - depart,
            sources_examinees=len(resultats),
            extraits_examines=[r.extrait.id for r in resultats],
        )

    texte = str(donnees.get("reponse", "")).strip()
    citations = _citations_valides(donnees.get("sources"), resultats)
    sources_citees = "\n".join(resultats[citation.numero - 1].extrait.contenu for citation in citations)

    refusee = (
        not texte
        or not citations
        # Un aveu d'ignorance reste une abstention, même accompagné d'une citation.
        or avoue_ignorance(texte)
        # La référence demandée doit figurer dans la source citée, sinon le modèle a lu
        # un autre document (constaté : le montant d'une facture voisine).
        or not references_respectees(question, sources_citees)
        # La réponse doit être ancrée dans la source : soit par la phrase recopiée, soit
        # parce que tous les chiffres avancés s'y retrouvent. Dernier rempart contre une
        # réponse venue de la culture générale du modèle.
        or not (
            citation_verifiee(str(donnees.get("citation", "")), sources_citees)
            or chiffres_ancres(texte, sources_citees)
        )
    )
    if refusee:
        if texte:
            logger.info("Réponse écartée par les vérifications : %r", texte[:120])
        return Reponse(
            texte=PHRASE_ABSTENTION,
            abstention=True,
            secondes=time.perf_counter() - depart,
            sources_examinees=len(resultats),
            extraits_examines=[r.extrait.id for r in resultats],
        )

    return Reponse(
        texte=texte,
        citations=citations,
        secondes=time.perf_counter() - depart,
        sources_examinees=len(resultats),
        extraits_examines=[r.extrait.id for r in resultats],
    )
