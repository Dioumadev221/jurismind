"""Mesure de la justesse des extractions structurées.

Les documents ont été fabriqués à partir de faits connus : on compare donc, champ par
champ, ce que l'IA a extrait à ce qui a servi à écrire l'acte. Trois indicateurs :

- **taux de remplissage** : part des champs attendus que l'IA a renseignés ;
- **justesse** : parmi les champs renseignés, ceux dont la valeur est exacte ;
- **erreurs** : champs renseignés avec une valeur fausse — les seuls vraiment coûteux, car
  un avocat pourrait les valider sans y regarder de près.

On distingue les documents lus directement de ceux passés par l'OCR : c'est là que se voit
le coût réel des scans.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.db.models import Document, Extraction
from jurismind.db.session import get_engine

CORRIGE = Path("data/simulation/verite.json")

# Correspondance entre les champs de nos schémas et les faits ayant servi à écrire l'acte.
CORRESPONDANCES: dict[str, dict[str, str]] = {
    "Facture": {
        "numero": "numero",
        "montant_total_fcfa": "montant",
        "date_acte": "date",
        "destinataire": "debiteur",
    },
    "MiseEnDemeure": {
        "destinataire": "destinataire",
        "montant_reclame_fcfa": "montant",
        "delai_jours": "delai_jours",
    },
    "OrdonnanceInjonctionDePayer": {
        "numero": "numero",
        "montant_fcfa": "montant",
        "debiteur": "debiteur",
    },
    "PvSignification": {
        "date_signification": "date_signification",
        "destinataire": "destinataire",
    },
    "Contrat": {
        "duree_mois": "duree_mois",
        "montant_annuel_fcfa": "montant_annuel",
        "preavis_resiliation_jours": "preavis_resiliation_jours",
        "type_contrat": "type",
    },
    "Jugement": {"montant_alloue_fcfa": "montant_alloue", "numero_rg": "rg"},
    "BailCommercial": {"loyer_mensuel_fcfa": "loyer_mensuel", "preneur": "preneur"},
    "Statuts": {"denomination": "denomination", "capital_fcfa": "capital", "gerant": "gerant"},
}


def _normaliser(valeur: Any) -> str:
    sans_accent = unicodedata.normalize("NFKD", str(valeur)).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sans_accent.lower()).split())


# Mots qui ne distinguent pas deux sociétés : « société Baobab Télécom » désigne bien
# « Baobab Télécom SARL », d'autant que l'OCR avale souvent la forme juridique.
MOTS_NEUTRES = {"societe", "sarl", "suarl", "sa", "sas", "gie", "la", "le", "les", "de", "du"}
RECOUVREMENT_MINIMAL = 0.7


def _mots_significatifs(valeur: Any) -> set[str]:
    return {mot for mot in _normaliser(valeur).split() if mot not in MOTS_NEUTRES}


def valeurs_equivalentes(extrait: Any, attendu: Any) -> bool:
    """Compare une valeur extraite à la valeur connue, sans exiger la même écriture."""
    if isinstance(attendu, int | float) or (isinstance(attendu, str) and attendu.isdigit()):
        chiffres_extraits = re.sub(r"\D", "", str(extrait))
        return bool(chiffres_extraits) and chiffres_extraits == re.sub(r"\D", "", str(attendu))

    gauche, droite = _normaliser(extrait), _normaliser(attendu)
    if not gauche or not droite:
        return False
    if gauche in droite or droite in gauche:
        return True

    # Sinon, on compare les mots qui distinguent réellement deux valeurs.
    mots_extraits, mots_attendus = _mots_significatifs(extrait), _mots_significatifs(attendu)
    if not mots_attendus:
        return False
    return len(mots_extraits & mots_attendus) / len(mots_attendus) >= RECOUVREMENT_MINIMAL


@dataclass
class BilanExtraction:
    attendus: int = 0
    renseignes: int = 0
    justes: int = 0
    erreurs: list[dict[str, Any]] = field(default_factory=list)
    par_scan: dict[str, dict[str, int]] = field(default_factory=dict)

    def compter(self, scan: bool, juste: bool, renseigne: bool) -> None:
        cle = "scan (OCR)" if scan else "document lu directement"
        compteurs = self.par_scan.setdefault(cle, {"attendus": 0, "renseignes": 0, "justes": 0})
        compteurs["attendus"] += 1
        compteurs["renseignes"] += int(renseigne)
        compteurs["justes"] += int(juste)

    def resume(self) -> dict[str, Any]:
        taux = lambda n, d: round(100 * n / d, 1) if d else 0.0
        return {
            "champs_attendus": self.attendus,
            "taux_de_remplissage": taux(self.renseignes, self.attendus),
            "justesse": taux(self.justes, self.renseignes),
            "champs_faux": len(self.erreurs),
            "detail_par_source": {
                source: {
                    "remplissage": taux(c["renseignes"], c["attendus"]),
                    "justesse": taux(c["justes"], c["renseignes"]),
                    "champs": c["attendus"],
                }
                for source, c in sorted(self.par_scan.items())
            },
        }


def faits_connus(corrige: Path = CORRIGE) -> dict[int, dict[str, Any]]:
    """Faits ayant servi à écrire chaque document, indexés par identifiant d'origine."""
    if not corrige.exists():
        raise FileNotFoundError(f"{corrige} manquant : lancer `python -m simulation`")
    monde = json.loads(corrige.read_text(encoding="utf-8"))
    return {
        document["id"]: {"faits": document["faits"], "scan": document["scan"]}
        for dossier in monde["dossiers"]
        for document in dossier["documents"]
    }


def evaluer_extractions(session: Session, corrige: Path = CORRIGE) -> BilanExtraction:
    """Compare toutes les extractions proposées aux faits connus."""
    connus = faits_connus(corrige)
    bilan = BilanExtraction()

    for extraction in session.scalars(select(Extraction).order_by(Extraction.id)):
        correspondance = CORRESPONDANCES.get(extraction.schema)
        document = session.get(Document, extraction.document_id)
        if correspondance is None or document is None or document.external_id is None:
            continue
        reference = connus.get(document.external_id)
        if reference is None:
            continue

        for champ, fait in correspondance.items():
            attendu = reference["faits"].get(fait)
            if attendu in (None, "", []):
                continue  # l'acte ne portait pas cette information
            bilan.attendus += 1
            extrait = extraction.donnees.get(champ)
            renseigne = extrait not in (None, "", [])
            juste = renseigne and valeurs_equivalentes(extrait, attendu)
            bilan.renseignes += int(renseigne)
            bilan.justes += int(juste)
            bilan.compter(reference["scan"], juste, renseigne)
            if renseigne and not juste:
                bilan.erreurs.append(
                    {
                        "document": document.titre,
                        "champ": champ,
                        "extrait": extrait,
                        "attendu": attendu,
                        "scan": reference["scan"],
                    }
                )
    return bilan


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--erreurs", action="store_true", help="afficher les champs faux")
    args = parser.parse_args()

    with Session(get_engine()) as session:
        bilan = evaluer_extractions(session)
    resume = bilan.resume()

    print("\n| Indicateur | Valeur |")
    print("|---|---|")
    print(f"| Champs attendus | {resume['champs_attendus']} |")
    print(f"| Taux de remplissage | {resume['taux_de_remplissage']} % |")
    print(f"| Justesse des champs renseignés | {resume['justesse']} % |")
    print(f"| Champs faux | {resume['champs_faux']} |")
    for source, mesures in resume["detail_par_source"].items():
        print(
            f"| {source} ({mesures['champs']} champs) | "
            f"remplissage {mesures['remplissage']} %, justesse {mesures['justesse']} % |"
        )

    if args.erreurs:
        print("\nChamps faux :")
        for erreur in bilan.erreurs:
            marque = " (scan)" if erreur["scan"] else ""
            print(f"  {erreur['document'][:48]:<50}{marque}")
            print(f"    {erreur['champ']} : extrait {erreur['extrait']!r}, attendu {erreur['attendu']!r}")


if __name__ == "__main__":
    main()
