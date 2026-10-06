"""Trie le courrier entrant et tranche les propositions de l'IA.

Usage :
    uv run python -m jurismind.agents.courrier trier
    uv run python -m jurismind.agents.courrier attente
    uv run python -m jurismind.agents.courrier valider 3
    uv run python -m jurismind.agents.courrier rejeter 4 --motif "mauvais dossier"

L'avocat ou l'assistant est désigné par --email ; sans lui, on prend le premier avocat
actif, car le tri du courrier n'appartient à aucun dossier en particulier.
"""

import argparse
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.agents.propositions import (
    DejaTranchee,
    PropositionIntrouvable,
    a_trancher,
    rejeter,
    valider,
)
from jurismind.agents.tri import resume_des_propositions, trier
from jurismind.db.models import Role, Utilisateur
from jurismind.db.session import get_engine, session_utilisateur


def _utilisateur(email: str | None) -> tuple[int, str]:
    """Qui agit. Le tri du courrier est ouvert aux avocats et aux assistants."""
    with Session(get_engine()) as session:
        if email:
            trouve = session.scalars(select(Utilisateur).where(Utilisateur.email == email)).one_or_none()
        else:
            trouve = session.scalars(
                select(Utilisateur)
                .where(Utilisateur.role == Role.AVOCAT, Utilisateur.actif)
                .order_by(Utilisateur.id)
            ).first()
        if trouve is None:
            raise SystemExit("Utilisateur introuvable : lancer la synchronisation")
        if trouve.role is Role.ADMIN:
            raise SystemExit("Un administrateur ne voit pas le courrier du cabinet")
        return trouve.id, trouve.nom_complet


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "action", choices=("trier", "attente", "valider", "rejeter"), help="ce qu'on veut faire"
    )
    parser.add_argument("proposition", nargs="?", type=int, help="numéro de la proposition à trancher")
    parser.add_argument("--email", help="qui agit (par défaut : le premier avocat actif)")
    parser.add_argument("--motif", default="", help="motif du rejet, conservé au journal")
    parser.add_argument("--limite", type=int, default=20, help="nombre d'emails à trier")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    utilisateur_id, nom = _utilisateur(args.email)
    print(f"Au nom de : {nom}\n")

    if args.action in ("valider", "rejeter") and args.proposition is None:
        raise SystemExit(f"Donner le numéro de la proposition à {args.action}")

    with session_utilisateur(utilisateur_id) as session:
        if args.action == "trier":
            reponse = trier(session, utilisateur_id, args.limite)
            print(reponse.texte)
            print(f"\nen {reponse.secondes:.0f}s")
        elif args.action == "attente":
            print(resume_des_propositions(a_trancher(session)))
        else:
            try:
                tranchee = (
                    valider(session, args.proposition, utilisateur_id)
                    if args.action == "valider"
                    else rejeter(session, args.proposition, utilisateur_id, args.motif)
                )
            except PropositionIntrouvable:
                raise SystemExit(f"Proposition {args.proposition} introuvable") from None
            except DejaTranchee as erreur:
                raise SystemExit(str(erreur)) from None
            print(f"#{tranchee.id} {tranchee.type} → {tranchee.statut}")
            print(f"   {tranchee.titre}")
            if tranchee.erreur:
                print(f"   échec de l'application : {tranchee.erreur}")
            if identifiant := tranchee.donnees.get("crm_task_id"):
                print(f"   tâche créée dans le CRM : {identifiant}")


if __name__ == "__main__":
    main()
