"""Mesure la fiabilité de JurisMind sur un jeu de questions dont on connaît les réponses.

Usage :
    uv run python -m jurismind.evaluation --questions 20
    uv run python -m jurismind.evaluation --questions 40 --extraits 5
"""

import argparse
import json
import logging
from pathlib import Path

from jurismind.evaluation.jeu import construire
from jurismind.evaluation.mesures import evaluer

SORTIE = Path("data/evaluation")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=int, default=20, help="taille du jeu")
    parser.add_argument("--extraits", type=int, default=4, help="extraits fournis au modèle")
    parser.add_argument("--graine", type=int, default=7, help="tirage reproductible")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    questions = construire(nombre=args.questions, graine=args.graine)
    bilan = evaluer(questions, extraits=args.extraits)
    resume = bilan.resume()

    print("\n| Indicateur | Valeur |")
    print("|---|---|")
    print(f"| Questions | {resume['questions']} |")
    print(f"| Rappel de la recherche | {resume['rappel_recherche']} % |")
    print(f"| Citation du bon document | {resume['citation_exacte']} % |")
    print(f"| Justesse des réponses | {resume['justesse']} % |")
    print(f"| Abstention correcte | {resume['abstention_correcte']} % |")
    print(f"| Réponses inventées | {resume['inventions']} |")
    print(f"| Silences alors que la source était là | {resume['silences_coupables']} |")
    print(f"| Temps moyen par question | {resume['secondes_moyennes']} s |")

    SORTIE.mkdir(parents=True, exist_ok=True)
    fichier = SORTIE / f"evaluation_{args.questions}q.json"
    fichier.write_text(json.dumps(bilan.en_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDétail par question : {fichier}")


if __name__ == "__main__":
    main()
