"""Préparer et servir la démonstration publique.

Sur la machine qui fait tourner les modèles (base indexée, Ollama démarré) :

    uv run python -m jurismind.demo enregistrer   # le scénario, appels aux modèles consignés
    uv run python -m jurismind.demo exporter      # la base figée dans demo/base.sql.gz

Sur le serveur public, au démarrage (fait par `docker/demo.sh`) :

    python -m jurismind.demo preparer             # charge l'export, ou remet la base à zéro
"""

from __future__ import annotations

import argparse
import json
import logging
import os

from jurismind.demo import ENREGISTREMENTS, EXPORT, SCENARIO
from jurismind.evaluation.jeu import CORRIGE


def _date_du_corpus() -> str:
    """Le jour où la simulation a « arrêté » le cabinet : c'est le jour de la démonstration."""
    return str(json.loads(CORRIGE.read_text(encoding="utf-8"))["reference"])


def enregistrer() -> None:
    # Avant toute lecture des réglages : ils sont lus une fois, puis gardés en mémoire.
    os.environ["LLM_ENREGISTREMENT"] = str(ENREGISTREMENTS)
    os.environ.setdefault("DATE_DU_CABINET", _date_du_corpus())
    ENREGISTREMENTS.unlink(missing_ok=True)

    from sqlalchemy.orm import Session

    from jurismind.core.config import get_settings
    from jurismind.db.session import get_engine
    from jurismind.demo.scenario import ecrire, executer, planifier

    reglages = get_settings()
    if reglages.llm_fournisseur == "demo":
        raise SystemExit("Enregistrer demande un vrai modèle : LLM_FOURNISSEUR=ollama ou openai.")
    with Session(get_engine()) as session:
        comptes, demandes = planifier(session)
    print(f"{len(demandes)} demandes à jouer, comptes : {', '.join(c.email for c in comptes)}")
    executer(comptes, demandes)
    ecrire(comptes, demandes, os.environ["DATE_DU_CABINET"])
    print(f"\nScénario : {SCENARIO}\nAppels consignés : {ENREGISTREMENTS}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("action", choices=["enregistrer", "exporter", "restaurer", "preparer"])
    parser.add_argument(
        "--conteneur", default="jurismind-postgres", help="conteneur de la base, pour pg_dump"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.action == "enregistrer":
        enregistrer()
        return

    from jurismind.demo import base

    if args.action == "exporter":
        chemin = base.exporter(conteneur=args.conteneur)
        print(f"Export : {chemin} ({chemin.stat().st_size / 1e6:.1f} Mo)")
    elif args.action == "restaurer":
        base.restaurer(EXPORT)
    else:
        base.preparer()


if __name__ == "__main__":
    main()
