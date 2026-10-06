"""Propose des extractions structurées pour les documents du cabinet.

Usage :
    uv run python -m jurismind.extraction --limite 10
    uv run python -m jurismind.extraction --limite 5 --rapide   # modèle rapide, pour essayer
    uv run python -m jurismind.extraction --dossier D2026-0028   # un dossier qui vient de bouger
"""

import argparse
import logging
import time

from sqlalchemy.orm import Session

from jurismind.db.session import get_engine
from jurismind.extraction.extracteur import documents_a_extraire, enregistrer, extraire
from jurismind.llm import Vitesse

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--limite", type=int, default=10, help="nombre de documents à traiter")
    parser.add_argument("--rapide", action="store_true", help="utiliser le petit modèle")
    parser.add_argument("--dossier", help="ne traiter que les actes de ce dossier, ex. D2026-0028")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    vitesse = Vitesse.RAPIDE if args.rapide else Vitesse.QUALITE
    depart = time.perf_counter()
    faits = douteux = 0

    with Session(get_engine()) as session:
        documents = documents_a_extraire(session, limite=args.limite, dossier=args.dossier)
        print(f"{len(documents)} document(s) à traiter\n")
        for document in documents:
            debut = time.perf_counter()
            proposition = extraire(document, vitesse=vitesse)
            if proposition is None:
                continue
            enregistrer(session, document, proposition)
            # Une campagne dure des dizaines de minutes sur CPU : chaque document est
            # enregistré aussitôt, pour que rien ne soit perdu en cas d'interruption.
            session.commit()
            faits += 1
            douteux += len(proposition.champs_douteux)
            alerte = (
                f" ! champs douteux : {', '.join(proposition.champs_douteux)}"
                if proposition.champs_douteux
                else ""
            )
            print(
                f"{document.titre[:52]:<54} {proposition.schema:<28} "
                f"{proposition.champs_remplis} champs  {time.perf_counter() - debut:5.1f}s{alerte}"
            )

    print(
        f"\n{faits} extraction(s) proposée(s), {douteux} champ(s) à relire, "
        f"en {time.perf_counter() - depart:.0f}s"
    )


if __name__ == "__main__":
    main()
