"""Lance la synchronisation depuis le logiciel du cabinet.

Usage : uv run python -m jurismind.connectors
"""

import logging

from jurismind.connectors.legacy import synchroniser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    bilan = synchroniser()

    tables = sorted(set(bilan.crees) | set(bilan.mis_a_jour) | set(bilan.ignores))
    largeur = max((len(t) for t in tables), default=0)
    print(f"{'table':<{largeur}}  créés  mis à jour  ignorés")
    for table in tables:
        print(
            f"{table:<{largeur}}  {bilan.crees.get(table, 0):>5}  "
            f"{bilan.mis_a_jour.get(table, 0):>10}  {bilan.ignores.get(table, 0):>7}"
        )
    print(f"\nfiches clients en double fusionnées : {bilan.doublons_fusionnes}")


if __name__ == "__main__":
    main()
