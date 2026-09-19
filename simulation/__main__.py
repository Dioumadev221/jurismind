"""Génère le système d'information « existant » du cabinet simulé.

Usage : uv run python -m simulation [--taille small|full] [--seed 42]

Produit :
- la base `legacy` (logiciel de gestion du cabinet) remplie ;
- data/cabinet/documents/, le serveur de fichiers (PDF, DOCX, scans) ;
- data/crm/crm.json, les données servies par le CRM factice ;
- data/simulation/verite.json, la version propre du monde (corrigé pour l'évaluation).
"""

import argparse
import dataclasses
import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jurismind.db.session import get_legacy_engine
from simulation.documents import generer_fichiers
from simulation.generateur import TAILLES, generer
from simulation.legacy.chargement import charger

DATA = Path("data")


def _json(obj: Any) -> Any:
    if isinstance(obj, date | datetime):
        return obj.isoformat()
    raise TypeError(type(obj))


def _ecrire(chemin: Path, contenu: Any) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(contenu, ensure_ascii=False, indent=2, default=_json),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--taille", choices=list(TAILLES), default="small")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sans-fichiers", action="store_true", help="ne pas produire les PDF/DOCX")
    args = parser.parse_args()

    monde = generer(args.taille, args.seed)
    defauts = charger(monde, get_legacy_engine(), args.seed)
    _ecrire(DATA / "crm" / "crm.json", monde.crm)
    _ecrire(
        DATA / "simulation" / "verite.json",
        {
            "taille": args.taille,
            "seed": args.seed,
            "defauts_legacy": defauts,
            **dataclasses.asdict(monde),
        },
    )

    nb_fichiers = 0
    if not args.sans_fichiers:
        racine = DATA / "cabinet" / "documents"
        shutil.rmtree(racine, ignore_errors=True)
        nb_fichiers = generer_fichiers(monde, racine)

    print(f"Cabinet simulé ({args.taille}, graine {args.seed}) – référence {monde.reference}")
    for table, n in defauts["comptes"].items():
        print(f"  legacy.{table:<24} {n}")
    for ressource, items in monde.crm.items():
        print(f"  crm.{ressource:<27} {len(items)}")
    print(f"  doublons clients introduits    {len(defauts['doublons_clients'])}")
    print(f"  fichiers de documents          {nb_fichiers}")


if __name__ == "__main__":
    main()
