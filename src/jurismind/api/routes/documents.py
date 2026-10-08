"""Les pièces : fiche, valeurs extraites (F5), et agent d'analyse (F8)."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from jurismind.agents import analyse as agent_document
from jurismind.agents.outils import extraction_du_document, fiche_document
from jurismind.api.schemas import (
    DemandeAgent,
    DemandeValidationExtraction,
    DocumentPublic,
    ReponseAgentPublique,
)
from jurismind.api.securite import IdentiteRequise, SessionRequise
from jurismind.db.models import Extraction
from jurismind.extraction.extracteur import valider

routeur = APIRouter(prefix="/documents", tags=["Documents"])

INTROUVABLE = "Document introuvable, ou son dossier ne vous est pas ouvert"


def _document_visible(session: SessionRequise, document_id: int) -> dict:
    fiche = fiche_document(session, document_id)
    if fiche is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=INTROUVABLE)
    return fiche


@routeur.get(
    "/{document_id}",
    response_model=DocumentPublic,
    summary="Fiche d'une pièce",
    responses={404: {"description": INTROUVABLE}},
)
def fiche(document_id: int, session: SessionRequise) -> DocumentPublic:
    """La fiche sans le texte intégral : `categorie_source` est la saisie du cabinet,
    `categorie_detectee` ce que JurisMind a reconnu en lisant la pièce."""
    return DocumentPublic.model_validate(_document_visible(session, document_id))


@routeur.get("/{document_id}/texte", response_model=dict, summary="Texte lu de la pièce")
def texte(document_id: int, session: SessionRequise) -> dict:
    """Le texte extrait du fichier, directement ou par OCR pour un scan."""
    detail = _document_visible(session, document_id)
    return {
        "document_id": document_id,
        "lu_par_ocr": detail["lu_par_ocr"],
        "caracteres": detail["caracteres"],
        "texte": detail["texte"],
    }


@routeur.get(
    "/{document_id}/extraction",
    response_model=dict,
    summary="Valeurs extraites de la pièce (F5)",
    responses={404: {"description": "Aucune extraction pour cette pièce"}},
)
def extraction(document_id: int, session: SessionRequise) -> dict:
    """Une extraction est une **proposition** : `relue` dit si un avocat l'a validée.

    `champs_douteux` liste les valeurs qui ne se retrouvent pas telles quelles dans le
    document : c'est là que l'avocat doit regarder en premier.
    """
    _document_visible(session, document_id)
    valeurs = extraction_du_document(session, document_id)
    if valeurs is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune extraction : lancer `python -m jurismind.extraction`",
        )
    return valeurs


@routeur.post(
    "/{document_id}/analyse",
    response_model=ReponseAgentPublique,
    summary="Agent d'analyse de documents (F8)",
)
def analyse(
    document_id: int, demande: DemandeAgent, session: SessionRequise, qui: IdentiteRequise
) -> ReponseAgentPublique:
    """Reconnaît le type de l'acte, le résume, et relève ce qui engage.

    Chaque point relevé est accompagné de la phrase du document qui le porte ; un point dont
    la citation ne se retrouve pas dans l'acte est supprimé. Avec une `demande` non vide, la
    route répond plutôt à cette question, bornée au dossier de la pièce. Compter 30 à 90 s.
    """
    _document_visible(session, document_id)
    reponse = agent_document.assister(session, qui.utilisateur_id, document_id, demande.demande)
    return ReponseAgentPublique(**asdict(reponse))


@routeur.post(
    "/{document_id}/extraction/validation",
    response_model=dict,
    summary="Valider les valeurs extraites, après relecture",
    responses={404: {"description": "Aucune extraction pour cette pièce"}},
)
def validation_extraction(
    document_id: int,
    demande: DemandeValidationExtraction,
    session: SessionRequise,
    qui: IdentiteRequise,
) -> dict:
    """Une extraction est une proposition ; cette route est l'endroit où un humain tranche.

    Les corrections envoyées écrasent les valeurs proposées, et un champ corrigé cesse
    d'être douteux. Une campagne d'extraction ultérieure n'écrasera pas cette version :
    c'est elle qui fait foi (ADR 0004).
    """
    _document_visible(session, document_id)
    extraction = session.scalars(
        select(Extraction)
        .where(Extraction.document_id == document_id)
        .order_by(Extraction.id.desc())
        .limit(1)
    ).first()
    if extraction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune extraction à valider pour cette pièce",
        )
    valider(session, extraction, qui.utilisateur_id, demande.corrections or None)
    session.flush()
    detail = extraction_du_document(session, document_id)
    return detail or {}
