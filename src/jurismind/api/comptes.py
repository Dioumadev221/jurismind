"""Donne un mot de passe aux comptes importés du vieux logiciel.

Les comptes repris par le connecteur portent une empreinte qu'aucun mot de passe ne peut
produire : ils existent, mais ils ne peuvent pas se connecter. Cette commande leur en attribue
un, tiré au hasard, et l'écrit dans un fichier **hors du dépôt** (`data/` est ignoré par git).
Le mot de passe n'est jamais affiché à l'écran ni inscrit au journal.

    uv run python -m jurismind.api.comptes --demo
    uv run python -m jurismind.api.comptes m.dieng@teranga-avocats.example
"""

import argparse
import logging
import secrets
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.api.securite import hacher
from jurismind.db.models import Role, Utilisateur
from jurismind.db.session import get_engine

logger = logging.getLogger(__name__)

FICHIER = Path("data/comptes-demo.txt")
# Trois mots de 4 octets : assez pour n'être pas devinable, assez court pour être recopié.
LONGUEUR = 4
ROLES_DEMO = (Role.AVOCAT, Role.ASSISTANT)
COMPTES_DEMO = 4


def mot_de_passe_tire() -> str:
    return "-".join(secrets.token_hex(LONGUEUR) for _ in range(3))


def attribuer(emails: list[str]) -> list[tuple[str, str, str]]:
    """Attribue un mot de passe à chaque compte. Rend (email, nom, mot de passe)."""
    attribues: list[tuple[str, str, str]] = []
    with Session(get_engine()) as session, session.begin():
        for email in emails:
            utilisateur = session.scalars(
                select(Utilisateur).where(Utilisateur.email == email.strip().lower())
            ).one_or_none()
            if utilisateur is None:
                logger.warning("Compte inconnu, ignoré : %s", email)
                continue
            mot_de_passe = mot_de_passe_tire()
            utilisateur.mot_de_passe_hash = hacher(mot_de_passe)
            attribues.append((utilisateur.email, utilisateur.nom_complet, mot_de_passe))
    return attribues


def comptes_de_demo() -> list[str]:
    """Quelques avocats et assistants actifs : de quoi montrer l'isolation à l'œuvre."""
    with Session(get_engine()) as session:
        return [
            email
            for email in session.scalars(
                select(Utilisateur.email)
                .where(Utilisateur.role.in_(ROLES_DEMO), Utilisateur.actif)
                .order_by(Utilisateur.role, Utilisateur.id)
                .limit(COMPTES_DEMO)
            ).all()
        ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("emails", nargs="*", help="comptes à doter d'un mot de passe")
    parser.add_argument("--demo", action="store_true", help="les premiers avocats et assistants actifs")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    emails = args.emails or (comptes_de_demo() if args.demo else [])
    if not emails:
        raise SystemExit("Donner au moins une adresse, ou --demo")

    attribues = attribuer(emails)
    if not attribues:
        raise SystemExit("Aucun compte trouvé")

    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    FICHIER.write_text(
        "# Mots de passe de démonstration — ce fichier n'est pas versionné.\n"
        + "\n".join(f"{email}\t{nom}\t{mot_de_passe}" for email, nom, mot_de_passe in attribues)
        + "\n",
        encoding="utf-8",
    )
    for email, nom, _ in attribues:
        print(f"  {email:<45} {nom}")
    print(f"\n{len(attribues)} compte(s) prêt(s). Mots de passe écrits dans {FICHIER}.")


if __name__ == "__main__":
    main()
