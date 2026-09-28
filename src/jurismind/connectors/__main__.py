"""Synchronise JurisMind avec les systèmes existants du cabinet.

Usage :
    uv run python -m jurismind.connectors              # logiciel de gestion + CRM
    uv run python -m jurismind.connectors --sans-crm   # logiciel de gestion seulement
"""

import argparse
import logging

from jurismind.connectors.crm import CrmIndisponible, synchroniser_crm
from jurismind.connectors.legacy import Bilan, synchroniser


def afficher(titre: str, bilan: Bilan) -> None:
    tables = sorted(set(bilan.crees) | set(bilan.mis_a_jour) | set(bilan.ignores))
    largeur = max((len(t) for t in tables), default=10)
    print(f"\n=== {titre} ===")
    print(f"{'table':<{largeur}}  créés  mis à jour  ignorés")
    for table in tables:
        print(
            f"{table:<{largeur}}  {bilan.crees.get(table, 0):>5}  "
            f"{bilan.mis_a_jour.get(table, 0):>10}  {bilan.ignores.get(table, 0):>7}"
        )
    if bilan.doublons_fusionnes:
        print(f"fiches clients en double fusionnées : {bilan.doublons_fusionnes}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sans-crm", action="store_true", help="ne pas interroger le CRM")
    parser.add_argument("--debug", action="store_true", help="afficher le détail des rapprochements")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s %(message)s"
    )

    afficher("Logiciel de gestion du cabinet", synchroniser())
    if not args.sans_crm:
        try:
            afficher("CRM", synchroniser_crm())
        except CrmIndisponible as erreur:
            # Le CRM est un complément : son indisponibilité ne doit pas bloquer le reste.
            print(f"\nCRM injoignable, synchronisation reportée : {erreur}")


if __name__ == "__main__":
    main()
