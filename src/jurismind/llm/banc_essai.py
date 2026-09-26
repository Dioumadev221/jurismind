"""Banc d'essai : compare plusieurs modèles sur des tâches juridiques, sur CETTE machine.

Usage : uv run python -m jurismind.llm.banc_essai qwen2.5:3b qwen2.5:latest llama3.1:8b

Chaque modèle passe les mêmes épreuves ; on mesure la justesse et le temps de réponse.
Objectif : choisir les modèles de `.env` avec des chiffres plutôt qu'au hasard.
"""

import argparse
import json as json_module
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jurismind.llm.fournisseur import modele_chat

EXTRAIT_PV = (
    "TRÈS IMPORTANT : le débiteur est informé qu'il dispose d'un délai de QUINZE (15) JOURS "
    "à compter de la présente signification pour former opposition devant la juridiction "
    "ayant rendu la décision, par acte extrajudiciaire. À défaut, l'ordonnance deviendra définitive."
)
EXTRAIT_MED = (
    "Notre client nous indique que vous restez lui devoir la somme de 13 750 000 FCFA au titre "
    "des factures FA-2025-978, FA-2025-143 et FA-2026-988. En conséquence, nous vous mettons en "
    "demeure de régler cette somme dans un délai de 8 jours à compter de la réception de la présente."
)
EMAIL = (
    "Objet : Loyers impayés – Baobab Immobilier SARL\n\n"
    "Maître, notre locataire ne paie plus son loyer de 850 000 FCFA depuis 7 mois. "
    "Nous souhaitons récupérer les sommes dues et, à défaut, le local."
)


@dataclass
class Epreuve:
    nom: str
    question: str
    json: bool
    verifier: Callable[[str], bool]


def _json_contient(reponse: str, champ: str, valeur: Any) -> bool:
    try:
        donnees = json_module.loads(reponse)
    except ValueError:
        return False
    return str(donnees.get(champ, "")).lower() == str(valeur).lower()


EPREUVES = [
    Epreuve(
        nom="question sur un extrait",
        question=(
            f"Extrait d'un acte d'huissier :\n{EXTRAIT_PV}\n\n"
            "De combien de jours dispose le débiteur pour former opposition ? "
            "Réponds uniquement à partir de l'extrait, en une phrase."
        ),
        json=False,
        verifier=lambda r: "15" in r or "quinze" in r.lower(),
    ),
    Epreuve(
        nom="abstention (l'info est absente)",
        question=(
            f"Extrait d'un acte d'huissier :\n{EXTRAIT_PV}\n\n"
            "Quel est le montant de la condamnation ? Si l'extrait ne le dit pas, "
            "réponds exactement : « Information absente de l'extrait. »"
        ),
        json=False,
        verifier=lambda r: "absente" in r.lower(),
    ),
    Epreuve(
        nom="extraction JSON",
        question=(
            f"Extrait d'une mise en demeure :\n{EXTRAIT_MED}\n\n"
            'Renvoie uniquement ce JSON : {"montant": nombre entier sans espaces, '
            '"devise": texte, "delai_jours": nombre entier}'
        ),
        json=True,
        verifier=lambda r: _json_contient(r, "montant", 13750000) and _json_contient(r, "delai_jours", 8),
    ),
    Epreuve(
        nom="classement d'un email",
        question=(
            f"Email reçu au cabinet :\n{EMAIL}\n\n"
            "Classe-le dans une seule matière :\n"
            "- recouvrement : faire payer des factures impayées (hors loyers)\n"
            "- bail : litige entre un bailleur et son locataire (loyers impayés, expulsion)\n"
            "- societe : création ou modification de société, cession de parts\n"
            "- contrat : rédaction ou négociation d'un contrat\n\n"
            'Renvoie uniquement ce JSON : {"matiere": la valeur choisie}'
        ),
        json=True,
        verifier=lambda r: _json_contient(r, "matiere", "bail"),
    ),
]


def essayer(nom_modele: str) -> dict[str, Any]:
    """Fait passer toutes les épreuves à un modèle et renvoie ses résultats."""
    resultats: dict[str, Any] = {"modele": nom_modele, "epreuves": [], "reussies": 0, "duree": 0.0}
    for epreuve in EPREUVES:
        modele = modele_chat(json=epreuve.json, nom=nom_modele)
        debut = time.perf_counter()
        try:
            reponse = str(modele.invoke(epreuve.question).content).strip()
            erreur = None
        except Exception as exc:  # noqa: BLE001 - modèle absent, Ollama arrêté…
            reponse, erreur = "", str(exc)[:120]
        duree = time.perf_counter() - debut

        reussie = erreur is None and epreuve.verifier(reponse)
        resultats["epreuves"].append(
            {"nom": epreuve.nom, "reussie": reussie, "duree": duree, "reponse": reponse, "erreur": erreur}
        )
        resultats["reussies"] += int(reussie)
        resultats["duree"] += duree
        print(f"  {'OK ' if reussie else 'RATÉ'} {epreuve.nom:32} {duree:6.1f}s")
    return resultats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modeles", nargs="+", help="noms des modèles Ollama à comparer")
    parser.add_argument("--details", action="store_true", help="afficher les réponses complètes")
    args = parser.parse_args()

    tous = []
    for nom in args.modeles:
        print(f"\n=== {nom} ===")
        tous.append(essayer(nom))

    print("\n| Modèle | Épreuves réussies | Temps total | Temps moyen |")
    print("|---|---|---|---|")
    for r in sorted(tous, key=lambda r: (-r["reussies"], r["duree"])):
        moyenne = r["duree"] / len(EPREUVES)
        print(f"| {r['modele']} | {r['reussies']}/{len(EPREUVES)} | {r['duree']:.0f}s | {moyenne:.0f}s |")

    if args.details:
        for r in tous:
            print(f"\n=== {r['modele']} ===")
            for e in r["epreuves"]:
                print(f"\n- {e['nom']} ({'réussie' if e['reussie'] else 'ratée'}) :")
                print(f"  {e['erreur'] or e['reponse'][:400]}")


if __name__ == "__main__":
    main()
