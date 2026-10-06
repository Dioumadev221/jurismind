"""Mesure le classement automatique des documents (F8).

On compare le type reconnu par l'IA à celui **saisi par le cabinet**. Attention à ce que
cela mesure : la saisie du cabinet n'est pas une vérité absolue — c'est précisément parce
qu'elle est parfois fausse ou laissée à « DIVERS » que la fonction existe. Ce chiffre est
donc un *taux d'accord*, pas un taux de justesse : un désaccord se lit, il ne se compte pas
automatiquement comme une erreur.

Les documents saisis « DIVERS » sont traités à part : il n'y a rien à confronter, et tout
type reconnu y est un gain.

    uv run python -m jurismind.evaluation.classement --par-type 2
"""

from __future__ import annotations

import argparse
import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.agents.analyse import CATEGORIES, categorie_valide, entete
from jurismind.agents.analyse import CONSIGNE_CLASSEMENT as CONSIGNE
from jurismind.agents.commun import lire_json, texte_attendu
from jurismind.db.models import Document, StatutTraitement
from jurismind.db.session import get_engine
from jurismind.llm import Vitesse, modele_chat

logger = logging.getLogger(__name__)

SANS_REFERENCE = "DIVERS"


@dataclass
class Bilan:
    """Résultat d'une campagne de classement."""

    accords: int = 0
    desaccords: int = 0
    refus: int = 0  # type hors liste, écarté par le code
    accords_ocr: int = 0
    total_ocr: int = 0
    divers_classes: int = 0
    divers_total: int = 0
    confusions: Counter[tuple[str, str]] = field(default_factory=Counter)
    secondes: float = 0.0

    @property
    def confrontes(self) -> int:
        return self.accords + self.desaccords + self.refus

    @property
    def taux_accord(self) -> float:
        return self.accords / self.confrontes if self.confrontes else 0.0

    @property
    def taux_accord_ocr(self) -> float:
        return self.accords_ocr / self.total_ocr if self.total_ocr else 0.0


def classer(document: Document) -> str | None:
    """Type reconnu pour ce document, ou `None` si la réponse est hors liste."""
    invite = CONSIGNE.format(
        types="\n".join(f"- {code} : {quoi}" for code, quoi in CATEGORIES.items()),
        titre=document.titre,
        texte=entete(document.texte or ""),
    )
    brut = str(modele_chat(Vitesse.RAPIDE, json=True).invoke(invite).content)
    return categorie_valide(texte_attendu(lire_json(brut), "type"))


def echantillon(session: Session, par_type: int) -> list[Document]:
    """Jusqu'à `par_type` documents de chaque catégorie saisie : un échantillon varié et stable."""
    documents = session.scalars(
        select(Document)
        .where(
            Document.statut_traitement == StatutTraitement.TRAITE,
            Document.texte.is_not(None),
            Document.categorie_source.is_not(None),
        )
        .order_by(Document.id)
    ).all()
    par_categorie: dict[str, list[Document]] = defaultdict(list)
    for document in documents:
        categorie = (document.categorie_source or "").upper()
        if categorie in CATEGORIES and len(par_categorie[categorie]) < par_type:
            par_categorie[categorie].append(document)
    return [document for lot in par_categorie.values() for document in lot]


def mesurer(session: Session, par_type: int) -> Bilan:
    bilan = Bilan()
    depart = time.perf_counter()
    for document in echantillon(session, par_type):
        attendu = (document.categorie_source or "").upper()
        reconnu = classer(document)
        marque = " (OCR)" if document.ocr_utilise else ""

        if attendu == SANS_REFERENCE:
            bilan.divers_total += 1
            if reconnu and reconnu != SANS_REFERENCE:
                bilan.divers_classes += 1
            print(f"DIVERS  -> {reconnu or 'hors liste':<22} {document.titre[:46]}{marque}")
            continue

        if document.ocr_utilise:
            bilan.total_ocr += 1
        if reconnu is None:
            bilan.refus += 1
            etat = "hors liste"
        elif reconnu == attendu:
            bilan.accords += 1
            bilan.accords_ocr += 1 if document.ocr_utilise else 0
            etat = "accord"
        else:
            bilan.desaccords += 1
            bilan.confusions[(attendu, reconnu)] += 1
            etat = f"!= {reconnu}"
        print(f"{attendu:<22} {etat:<26} {document.titre[:46]}{marque}")
    bilan.secondes = time.perf_counter() - depart
    return bilan


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--par-type", type=int, default=2, help="documents par catégorie saisie")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    with Session(get_engine()) as session:
        bilan = mesurer(session, args.par_type)

    print(f"\nDocuments confrontés à la saisie du cabinet : {bilan.confrontes}")
    print(f"  accord            : {bilan.accords} ({100 * bilan.taux_accord:.1f} %)")
    print(f"  désaccord         : {bilan.desaccords}")
    print(f"  réponse hors liste: {bilan.refus} (écartée par le code)")
    if bilan.total_ocr:
        print(
            f"  dont scans (OCR)  : {bilan.accords_ocr}/{bilan.total_ocr} "
            f"({100 * bilan.taux_accord_ocr:.1f} %)"
        )
    if bilan.divers_total:
        print(
            f"\nDocuments saisis « DIVERS » : {bilan.divers_classes}/{bilan.divers_total} "
            "ont reçu un type exploitable"
        )
    if bilan.confusions:
        print("\nDésaccords les plus fréquents (saisi -> reconnu) :")
        for (attendu, reconnu), nombre in bilan.confusions.most_common(8):
            print(f"  {attendu} -> {reconnu} : {nombre}")
    print(f"\nen {bilan.secondes:.0f}s")


if __name__ == "__main__":
    main()
