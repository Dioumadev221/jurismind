"""Vérifie les conflits d'intérêts du cabinet.

Usage :
    uv run python -m jurismind.conformite balayer
    uv run python -m jurismind.conformite dossier D2024-0007
    uv run python -m jurismind.conformite nom "Sahel BTP SAS"

Le contrôle voit **tout le cabinet**, y compris les dossiers fermés au demandeur : sans cela
il manquerait précisément les conflits qu'il doit trouver. En contrepartie il ne nomme que
les dossiers auxquels le demandeur a déjà accès, compte les autres, et s'inscrit au journal.
"""

import argparse
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.conformite.conflits import Niveau, balayer, conflits_du_dossier, verifier_identite
from jurismind.db.models import Role, Utilisateur
from jurismind.db.session import get_engine


def _utilisateur(email: str | None) -> tuple[int, str]:
    with Session(get_engine()) as session:
        requete = select(Utilisateur).where(Utilisateur.actif)
        if email:
            requete = requete.where(Utilisateur.email == email)
        else:
            requete = requete.where(Utilisateur.role == Role.AVOCAT).order_by(Utilisateur.id)
        trouve = session.scalars(requete).first()
        if trouve is None:
            raise SystemExit("Utilisateur introuvable")
        return trouve.id, trouve.nom_complet


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("action", choices=("balayer", "dossier", "nom"))
    parser.add_argument("cible", nargs="?", help="référence du dossier, ou nom à vérifier")
    parser.add_argument("--email", help="qui demande (par défaut : le premier avocat actif)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    utilisateur_id, nom = _utilisateur(args.email)
    print(f"Contrôle demandé par : {nom}\n")

    if args.action == "balayer":
        resultats = balayer(utilisateur_id)
        for reference, conflit in resultats:
            print(f"{reference}  {conflit.ligne()}")
        certains = sum(1 for _, c in resultats if c.niveau is Niveau.CERTAIN)
        print(
            f"\n{len(resultats)} signalement(s) : {certains} certain(s), "
            f"{len(resultats) - certains} à vérifier."
        )
        if not resultats:
            print("Aucune partie adverse ne porte le nom d'un client du cabinet.")
        return

    if args.cible is None:
        raise SystemExit(f"Donner une cible pour l'action « {args.action} »")

    if args.action == "dossier":
        try:
            intitule, conflits = conflits_du_dossier(utilisateur_id, args.cible)
        except LookupError as erreur:
            raise SystemExit(str(erreur)) from None
        print(f"{args.cible} — {intitule}")
    else:
        conflits = verifier_identite(utilisateur_id, args.cible)
        print(f"Vérification de : {args.cible}")

    for conflit in conflits:
        print(f"  {conflit.ligne()}")
    if not conflits:
        print("  Aucun conflit détecté.")


if __name__ == "__main__":
    main()
