"""Ce que les agents ont le droit de lire, et comment.

Chaque outil prend la session ouverte **au nom de l'utilisateur** : PostgreSQL applique
l'isolation, et l'agent ne peut pas la contourner, même en écrivant une requête maladroite.

Ces outils renvoient des faits tirés de la base — dates, montants, statuts — que le modèle
n'a plus qu'à mettre en forme. Un fait lu en base ne peut pas être inventé.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jurismind.db.models import (
    Client,
    Communication,
    Document,
    Dossier,
    ElementCrm,
    Extraction,
    Partie,
    SensEchange,
)


@dataclass
class Evenement:
    """Un fait daté du dossier, tiré de la base : rien ici n'est produit par un modèle."""

    date: date
    type: str  # document | echange | etape
    libelle: str
    detail: str | None = None
    document_id: int | None = None
    communication_id: int | None = None

    def ligne(self) -> str:
        detail = f" — {self.detail}" if self.detail else ""
        return f"{self.date:%d/%m/%Y} : {self.libelle}{detail}"


def fiche_dossier(session: Session, dossier_id: int) -> dict[str, Any] | None:
    """Carte d'identité du dossier. `None` si l'utilisateur n'y a pas accès."""
    dossier = session.get(Dossier, dossier_id)
    if dossier is None:
        return None  # invisible pour cet utilisateur : l'isolation a joué

    client = session.get(Client, dossier.client_id)
    parties = session.scalars(select(Partie).where(Partie.dossier_id == dossier_id)).all()
    documents = session.scalar(
        select(func.count()).select_from(Document).where(Document.dossier_id == dossier_id)
    )
    echanges = session.scalar(
        select(func.count()).select_from(Communication).where(Communication.dossier_id == dossier_id)
    )
    return {
        "reference": dossier.reference,
        "intitule": dossier.intitule,
        "client": client.nom if client else None,
        "type": str(dossier.type),
        "matiere": dossier.matiere,
        "statut": str(dossier.statut),
        "date_ouverture": dossier.date_ouverture,
        "date_cloture": dossier.date_cloture,
        "juridiction": dossier.juridiction,
        "numero_rg": dossier.numero_rg,
        "enjeu_fcfa": dossier.enjeu_fcfa,
        "confidentiel": dossier.confidentiel,
        "parties": [{"qualite": str(p.qualite), "nom": p.nom} for p in parties],
        "nombre_documents": documents or 0,
        "nombre_echanges": echanges or 0,
    }


def evenements_du_dossier(session: Session, dossier_id: int, limite: int = 60) -> list[Evenement]:
    """Chronologie du dossier, **construite par le code** à partir des dates en base."""
    evenements: list[Evenement] = []

    documents = session.scalars(
        select(Document).where(Document.dossier_id == dossier_id).order_by(Document.date_document)
    ).all()
    for document in documents:
        if document.date_document is None:
            continue
        sens_document = {"entrant": "reçu", "sortant": "envoyé", "interne": "rédigé"}
        evenements.append(
            Evenement(
                date=document.date_document,
                type="document",
                libelle=document.titre,
                detail=sens_document.get(str(document.sens)),
                document_id=document.id,
            )
        )

    echanges = session.scalars(
        select(Communication)
        .where(Communication.dossier_id == dossier_id)
        .order_by(Communication.date_echange)
    ).all()
    for echange in echanges:
        entrant = echange.sens is SensEchange.ENTRANT
        interlocuteur = (
            echange.expediteur if entrant else next(iter(echange.destinataires or []), None)
        )
        sens_echange = "reçu de" if entrant else "adressé à"
        evenements.append(
            Evenement(
                date=echange.date_echange.date(),
                type="echange",
                libelle=echange.objet or f"{echange.canal} sans objet",
                detail=f"{sens_echange} {interlocuteur}" if interlocuteur else None,
                communication_id=echange.id,
            )
        )

    evenements.sort(key=lambda evenement: evenement.date)
    return evenements[-limite:]


def donnees_extraites(session: Session, dossier_id: int) -> list[dict[str, Any]]:
    """Valeurs tirées des actes du dossier (montants, délais, parties), avec leur statut."""
    lignes = session.execute(
        select(Extraction, Document.titre)
        .join(Document, Extraction.document_id == Document.id)
        .where(Document.dossier_id == dossier_id)
        .order_by(Document.date_document)
    ).all()
    return [
        {
            "document": titre,
            "schema": extraction.schema,
            "donnees": {k: v for k, v in extraction.donnees.items() if v not in (None, "", [])},
            "relue": extraction.relue,
            "champs_douteux": extraction.champs_douteux,
        }
        for extraction, titre in lignes
    ]


def elements_crm_du_client(session: Session, client_id: int, limite: int = 8) -> list[dict[str, Any]]:
    """Ce que le CRM sait du client : opportunités, comptes rendus de rendez-vous, tâches."""
    elements = session.scalars(
        select(ElementCrm)
        .where(ElementCrm.client_id == client_id)
        .order_by(ElementCrm.date_element.desc())
        .limit(limite)
    ).all()
    return [
        {
            "type": str(element.type),
            "titre": element.titre,
            "contenu": element.contenu,
            "date": element.date_element,
            "statut": element.statut,
            "montant_fcfa": element.montant_fcfa,
        }
        for element in elements
    ]
