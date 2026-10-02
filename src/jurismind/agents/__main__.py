"""Interroge l'agent d'assistance sur un dossier.

Usage :
    uv run python -m jurismind.agents D2026-0024
    uv run python -m jurismind.agents D2026-0024 "chronologie"
    uv run python -m jurismind.agents D2026-0024 "Le débiteur a-t-il formé opposition ?"
"""

import argparse
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.agents.dossier import assister
from jurismind.db.models import AccesDossier, Dossier, Utilisateur
from jurismind.db.session import get_engine, session_utilisateur


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dossier", help="référence du dossier, ex. D2026-0024")
    parser.add_argument("demande", nargs="?", default="", help="question, ou vide pour une synthèse")
    parser.add_argument("--email", help="avocat qui pose la question (par défaut : le responsable)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    with Session(get_engine()) as session:
        dossier = session.scalars(select(Dossier).where(Dossier.reference == args.dossier)).one_or_none()
        if dossier is None:
            raise SystemExit(f"Dossier {args.dossier} introuvable")
        trouve: Utilisateur | None
        if args.email:
            trouve = session.scalars(select(Utilisateur).where(Utilisateur.email == args.email)).one()
        else:
            trouve = session.scalars(
                select(Utilisateur)
                .join(AccesDossier, AccesDossier.utilisateur_id == Utilisateur.id)
                .where(AccesDossier.dossier_id == dossier.id, AccesDossier.est_responsable)
            ).first()
        if trouve is None:
            raise SystemExit("Aucun avocat responsable : lancer la synchronisation")
        utilisateur = trouve
        dossier_id, utilisateur_id = dossier.id, utilisateur.id
        intitule, nom = dossier.intitule, utilisateur.nom_complet

    print(f"Dossier {args.dossier} — {intitule}")
    print(f"Au nom de : {nom}\n")

    with session_utilisateur(utilisateur_id) as session:
        reponse = assister(session, utilisateur_id, dossier_id, args.demande)

    print(
        f"[{reponse.intention}] en {reponse.secondes:.0f}s" + (" — abstention" if reponse.abstention else "")
    )
    print(reponse.texte)
    for citation in reponse.citations:
        print(f"   [{citation['numero']}] {citation['reference']}")


if __name__ == "__main__":
    main()
