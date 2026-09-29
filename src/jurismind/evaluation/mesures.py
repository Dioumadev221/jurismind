"""Mesure de la fiabilité : la recherche trouve-t-elle, et la réponse dit-elle vrai ?

Quatre indicateurs, tous calculés sur le jeu d'évaluation (donc vérifiables et publiables) :

- **rappel de la recherche** : le document qui porte la réponse est-il retrouvé ?
- **justesse** : la valeur exacte (montant, délai, date) figure-t-elle dans la réponse ?
- **abstention correcte** : sur les questions sans réponse possible, le système se tait-il ?
- **silence coupable** : cas où il s'abstient alors que la réponse était retrouvable.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.db.models import Document, Utilisateur
from jurismind.db.session import get_engine, session_utilisateur
from jurismind.evaluation.jeu import Question
from jurismind.rag import Reponse, repondre
from jurismind.retrieval import Filtres

logger = logging.getLogger(__name__)


# Un modèle écrit souvent les petits nombres en toutes lettres : la mesure doit le voir.
NOMBRES_EN_LETTRES = {
    "1": "un",
    "2": "deux",
    "3": "trois",
    "4": "quatre",
    "5": "cinq",
    "6": "six",
    "7": "sept",
    "8": "huit",
    "9": "neuf",
    "10": "dix",
    "15": "quinze",
    "20": "vingt",
    "30": "trente",
    "60": "soixante",
    "90": "quatre-vingt-dix",
}


def normaliser_valeur(valeur: str) -> str:
    """« 2 000 000 FCFA » et « 2000000 » doivent se comparer : on ne garde que les chiffres."""
    return re.sub(r"[^0-9/]", "", valeur)


def valeur_presente(attendu: str, texte: str) -> bool:
    cible = normaliser_valeur(attendu)
    if cible and cible in normaliser_valeur(texte):
        return True
    en_lettres = NOMBRES_EN_LETTRES.get(cible, "")
    return bool(en_lettres) and en_lettres in texte.lower()


@dataclass
class Resultat:
    question: str
    categorie: str
    attendu: list[str]
    reponse: str
    abstention: bool
    juste: bool
    source_trouvee: bool | None  # le bon document est-il parmi les extraits examinés ?
    source_citee: bool | None  # ... et a-t-il été cité dans la réponse ?
    citations: int
    secondes: float


@dataclass
class Bilan:
    resultats: list[Resultat] = field(default_factory=list)

    def _sur(self, condition: Any) -> list[Resultat]:
        return [r for r in self.resultats if condition(r)]

    @property
    def avec_reponse(self) -> list[Resultat]:
        return self._sur(lambda r: r.attendu)

    @property
    def sans_reponse(self) -> list[Resultat]:
        return self._sur(lambda r: not r.attendu)

    def taux(self, numerateur: int, denominateur: int) -> float:
        return 100 * numerateur / denominateur if denominateur else 0.0

    @property
    def rappel(self) -> float:
        """Le document qui porte la réponse figure-t-il parmi les extraits examinés ?"""
        concernes = self._sur(lambda r: r.source_trouvee is not None)
        return self.taux(sum(1 for r in concernes if r.source_trouvee), len(concernes))

    @property
    def citation_exacte(self) -> float:
        """Et la réponse cite-t-elle bien ce document ?"""
        concernes = self._sur(lambda r: r.source_citee is not None and not r.abstention)
        return self.taux(sum(1 for r in concernes if r.source_citee), len(concernes))

    @property
    def justesse(self) -> float:
        return self.taux(sum(1 for r in self.avec_reponse if r.juste), len(self.avec_reponse))

    @property
    def abstention_correcte(self) -> float:
        return self.taux(sum(1 for r in self.sans_reponse if r.abstention), len(self.sans_reponse))

    @property
    def silences_coupables(self) -> int:
        """Questions auxquelles on pouvait répondre, mais où le système s'est tu."""
        return sum(1 for r in self.avec_reponse if r.abstention and r.source_trouvee)

    @property
    def inventions(self) -> int:
        """Le pire cas : une réponse affirmative et fausse."""
        return sum(1 for r in self.avec_reponse if not r.abstention and not r.juste)

    @property
    def secondes_moyennes(self) -> float:
        return sum(r.secondes for r in self.resultats) / len(self.resultats) if self.resultats else 0.0

    def resume(self) -> dict[str, Any]:
        return {
            "questions": len(self.resultats),
            "rappel_recherche": round(self.rappel, 1),
            "citation_exacte": round(self.citation_exacte, 1),
            "justesse": round(self.justesse, 1),
            "abstention_correcte": round(self.abstention_correcte, 1),
            "silences_coupables": self.silences_coupables,
            "inventions": self.inventions,
            "secondes_moyennes": round(self.secondes_moyennes, 1),
        }

    def en_json(self) -> dict[str, Any]:
        return {"resume": self.resume(), "detail": [asdict(r) for r in self.resultats]}


def _utilisateur_de(session: Session, avocat_externe: int | None) -> int | None:
    if avocat_externe is None:
        return None
    return session.scalar(select(Utilisateur.id).where(Utilisateur.external_id == avocat_externe))


def _documents_cites(reponse: Reponse, session: Session) -> set[int]:
    """Identifiants d'origine des documents réellement utilisés par la réponse."""
    if not reponse.citations:
        return set()
    from jurismind.db.models import Extrait

    externes = session.scalars(
        select(Document.external_id)
        .join(Extrait, Extrait.document_id == Document.id)
        .where(Extrait.id.in_([c.extrait_id for c in reponse.citations]))
    )
    return {identifiant for identifiant in externes if identifiant is not None}


def _documents_retrouves(session: Session, extrait_ids: list[int]) -> set[int]:
    from jurismind.db.models import Extrait

    externes = session.scalars(
        select(Document.external_id)
        .join(Extrait, Extrait.document_id == Document.id)
        .where(Extrait.id.in_(extrait_ids))
    )
    return {identifiant for identifiant in externes if identifiant is not None}


def evaluer_question(question: Question, extraits: int = 4) -> Resultat:
    """Pose la question au nom de l'avocat responsable et compare à la réponse connue."""
    with Session(get_engine()) as session:
        utilisateur_id = _utilisateur_de(session, question.avocat_attendu)
    if utilisateur_id is None:
        raise RuntimeError(f"Avocat {question.avocat_attendu} introuvable : synchronisation manquante ?")

    debut = time.perf_counter()
    with session_utilisateur(utilisateur_id) as session:
        reponse = repondre(session, question.question, filtres=Filtres(), extraits=extraits)
        cites = _documents_cites(reponse, session)
        examines = _documents_retrouves(session, reponse.extraits_examines)

    juste = not question.sans_reponse and all(
        valeur_presente(valeur, reponse.texte) for valeur in question.attendu
    )
    attendu = question.document_attendu
    source_trouvee = None if attendu is None else attendu in examines
    source_citee = None if attendu is None else attendu in cites

    return Resultat(
        question=question.question,
        categorie=question.categorie,
        attendu=question.attendu,
        reponse=reponse.texte,
        abstention=reponse.abstention,
        juste=juste and not reponse.abstention,
        source_trouvee=source_trouvee,
        source_citee=source_citee,
        citations=len(reponse.citations),
        secondes=time.perf_counter() - debut,
    )


def evaluer(questions: list[Question], extraits: int = 4) -> Bilan:
    bilan = Bilan()
    for rang, question in enumerate(questions, start=1):
        resultat = evaluer_question(question, extraits=extraits)
        bilan.resultats.append(resultat)
        logger.info(
            "%s/%s %-11s %-6s %s",
            rang,
            len(questions),
            resultat.categorie,
            "abst." if resultat.abstention else ("juste" if resultat.juste else "FAUX"),
            question.question[:70],
        )
    return bilan
