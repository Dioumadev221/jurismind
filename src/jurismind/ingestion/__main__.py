"""Lit les documents du cabinet et prépare la recherche.

Usage :
    uv run python -m jurismind.ingestion                      # tout : lecture + vecteurs
    uv run python -m jurismind.ingestion --limite 20          # 20 documents seulement
    uv run python -m jurismind.ingestion --sans-vecteurs      # lecture et découpage seuls
    uv run python -m jurismind.ingestion --vecteurs 500       # reprendre 500 vecteurs
"""

import argparse
import logging

from jurismind.ingestion.lecture import ocr_disponible
from jurismind.ingestion.pipeline import ingerer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limite", type=int, help="nombre de documents à lire")
    parser.add_argument("--vecteurs", type=int, help="nombre de vecteurs à calculer")
    parser.add_argument("--sans-vecteurs", action="store_true", help="ne pas calculer les vecteurs")
    parser.add_argument("--force", action="store_true", help="relire même les fichiers inchangés")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not ocr_disponible():
        print("Attention : Tesseract est introuvable, les scans ne pourront pas être lus.")

    bilan = ingerer(
        limite=args.limite,
        force=args.force,
        avec_vecteurs=not args.sans_vecteurs,
        limite_vecteurs=args.vecteurs,
    )

    print(
        f"\ndocuments lus        {bilan.documents_lus}"
        f"\n  dont scans (OCR)   {bilan.scans_ocr}"
        f"\n  scans en attente   {bilan.scans_en_attente}"
        f"\n  inchangés, ignorés {bilan.documents_ignores}"
        f"\n  en erreur          {bilan.documents_en_erreur}"
        f"\néchanges lus         {bilan.communications_lues}"
        f"\nextraits créés       {bilan.extraits_crees}"
        f"\nvecteurs calculés    {bilan.vecteurs_calcules}"
        f"\ndurée                {bilan.secondes:.0f}s"
    )
    for erreur_lecture in bilan.erreurs[:10]:
        print(f"  ! {erreur_lecture}")


if __name__ == "__main__":
    main()
