"""Interroge les agents depuis la ligne de commande.

Usage :
    uv run python -m jurismind.agents dossier D2026-0024
    uv run python -m jurismind.agents dossier D2026-0024 "chronologie"
    uv run python -m jurismind.agents dossier D2026-0024 "Le débiteur a-t-il formé opposition ?"
    uv run python -m jurismind.agents client "Sine Services SA"
    uv run python -m jurismind.agents client "Sine Services SA" "points d'attention"
    uv run python -m jurismind.agents document D2026-0024   # liste les pièces du dossier
    uv run python -m jurismind.agents document 422
    uv run python -m jurismind.agents document D2026-0024   # liste les pièces du dossier
    uv run python -m jurismind.agents document 422 "Quel délai est accordé ?"
"""

import argparse
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.agents import analyse as agent_document
from jurismind.agents import client as agent_client
from jurismind.agents import dossier as agent_dossier
from jurismind.agents.commun import ReponseAgent
from jurismind.agents.outils import documents_du_dossier, trouver_client
from jurismind.db.models import AccesDossier, Client, Document, Dossier, Utilisateur
from jurismind.db.session import get_engine, session_utilisateur


def _utilisateur(session: Session, email: str | None, dossier_ids: list[int]) -> Utilisateur:
    """L'avocat qui pose la question : celui demandé, sinon un responsable des dossiers visés."""
    if email:
        return session.scalars(select(Utilisateur).where(Utilisateur.email == email)).one()
    trouve = session.scalars(
        select(Utilisateur)
        .join(AccesDossier, AccesDossier.utilisateur_id == Utilisateur.id)
        .where(AccesDossier.dossier_id.in_(dossier_ids or [0]), AccesDossier.est_responsable)
    ).first()
    if trouve is None:
        raise SystemExit("Aucun avocat responsable : lancer la synchronisation")
    return trouve


def _cible_dossier(session: Session, reference: str, email: str | None) -> tuple[int, int, str]:
    dossier = session.scalars(select(Dossier).where(Dossier.reference == reference)).one_or_none()
    if dossier is None:
        raise SystemExit(f"Dossier {reference} introuvable")
    utilisateur = _utilisateur(session, email, [dossier.id])
    return dossier.id, utilisateur.id, f"Dossier {reference} — {dossier.intitule}"


def _cible_client(session: Session, nom: str, email: str | None) -> tuple[int, int, str]:
    client_id = trouver_client(session, nom)
    if client_id is None:
        raise SystemExit(f"Client « {nom} » introuvable ou ambigu : donner le nom complet")
    nom_client = session.scalars(select(Client.nom).where(Client.id == client_id)).one()
    dossier_ids = list(session.scalars(select(Dossier.id).where(Dossier.client_id == client_id)).all())
    utilisateur = _utilisateur(session, email, dossier_ids)
    return client_id, utilisateur.id, f"Client {nom_client}"


def _cible_document(session: Session, identifiant: str, email: str | None) -> tuple[int, int, str]:
    """Résout un identifiant de document, ou liste les pièces d'un dossier pour en choisir une."""
    if not identifiant.isdigit():
        dossier = session.scalars(select(Dossier).where(Dossier.reference == identifiant)).one_or_none()
        if dossier is None:
            raise SystemExit("Donner un identifiant de document (ex. 422) ou une référence de dossier")
        print(f"Pièces du dossier {dossier.reference} :")
        for piece in documents_du_dossier(session, dossier.id):
            date_piece = f"{piece['date_document']:%d/%m/%Y}" if piece["date_document"] else "sans date"
            print(f"  {piece['id']:>4}  {date_piece}  {piece['categorie_source'] or '':<18} {piece['titre']}")
        raise SystemExit(0)
    document = session.get(Document, int(identifiant))
    if document is None:
        raise SystemExit(f"Document {identifiant} introuvable")
    utilisateur = _utilisateur(session, email, [document.dossier_id])
    return document.id, utilisateur.id, f"Document {document.id} — {document.titre}"


def _afficher(reponse: ReponseAgent) -> None:
    print(
        f"[{reponse.intention}] en {reponse.secondes:.0f}s" + (" — abstention" if reponse.abstention else "")
    )
    print(reponse.texte)
    for citation in reponse.citations:
        print(f"   [{citation['numero']}] {citation['reference']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("agent", choices=("dossier", "client", "document"), help="agent à interroger")
    parser.add_argument("cible", help="référence du dossier, nom du client, ou identifiant du document")
    parser.add_argument("demande", nargs="?", default="", help="question, ou vide pour une synthèse")
    parser.add_argument("--email", help="avocat qui pose la question (par défaut : un responsable)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # Première session avec la clé propriétaire : seulement pour identifier la cible et l'avocat.
    with Session(get_engine()) as session:
        trouver = {
            "dossier": _cible_dossier,
            "client": _cible_client,
            "document": _cible_document,
        }[args.agent]
        cible_id, utilisateur_id, titre = trouver(session, args.cible, args.email)
        nom = session.scalars(select(Utilisateur.nom_complet).where(Utilisateur.id == utilisateur_id)).one()

    print(f"{titre}\nAu nom de : {nom}\n")

    # Tout le travail de l'agent se fait avec les droits de cet utilisateur.
    with session_utilisateur(utilisateur_id) as session:
        module = {
            "dossier": agent_dossier,
            "client": agent_client,
            "document": agent_document,
        }[args.agent]
        _afficher(module.assister(session, utilisateur_id, cible_id, args.demande))


if __name__ == "__main__":
    main()
