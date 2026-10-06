"""Les clients : fiche, points d'attention, et agent d'intelligence client (F6)."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, status

from jurismind.agents import client as agent_client
from jurismind.agents.outils import (
    derniers_echanges,
    dossiers_du_client,
    fiche_client,
    points_attention,
    trouver_client,
)
from jurismind.api.schemas import (
    DemandeAgent,
    DossierPublic,
    PointAttentionPublic,
    ReponseAgentPublique,
)
from jurismind.api.securite import IdentiteRequise, SessionRequise

routeur = APIRouter(prefix="/clients", tags=["Clients"])

INTROUVABLE = "Client introuvable, ou aucun de ses dossiers ne vous est ouvert"


def _client_visible(session: SessionRequise, client_id: int) -> dict:
    fiche = fiche_client(session, client_id)
    if fiche is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=INTROUVABLE)
    return fiche


@routeur.get("/recherche", response_model=dict, summary="Retrouver un client par son nom")
def chercher(
    session: SessionRequise,
    nom: str = Query(description="Nom, même approximatif", examples=["Sine Services"]),
) -> dict:
    """Un nom qui désigne plusieurs clients ne renvoie rien : mieux vaut préciser que se tromper."""
    client_id = trouver_client(session, nom)
    if client_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Aucun client — ou plusieurs — ne correspond à « {nom} »",
        )
    return {"client_id": client_id, **_client_visible(session, client_id)}


@routeur.get(
    "/{client_id}",
    response_model=dict,
    summary="Fiche d'un client",
    responses={404: {"description": INTROUVABLE}},
)
def fiche(client_id: int, session: SessionRequise) -> dict:
    """Le champ `dossiers_visibles` ne compte que ce que l'utilisateur a le droit de voir."""
    return _client_visible(session, client_id)


@routeur.get("/{client_id}/dossiers", response_model=list[DossierPublic], summary="Ses dossiers")
def dossiers(client_id: int, session: SessionRequise) -> list[DossierPublic]:
    _client_visible(session, client_id)
    return [DossierPublic.model_validate(ligne) for ligne in dossiers_du_client(session, client_id)]


@routeur.get("/{client_id}/echanges", response_model=list[dict], summary="Ses derniers échanges")
def echanges(
    client_id: int, session: SessionRequise, limite: int = Query(default=8, ge=1, le=50)
) -> list[dict]:
    _client_visible(session, client_id)
    return derniers_echanges(session, client_id, limite)


@routeur.get(
    "/{client_id}/attention",
    response_model=list[PointAttentionPublic],
    summary="Ce qui mérite l'attention de l'avocat",
)
def attention(client_id: int, session: SessionRequise) -> list[PointAttentionPublic]:
    """Déduits des données par des règles, jamais demandés à un modèle (ADR 0006).

    Chaque point remonte à la date, au montant ou au statut qui l'a déclenché. Aucun appel au
    modèle : la réponse est immédiate.
    """
    _client_visible(session, client_id)
    return [PointAttentionPublic(**asdict(point)) for point in points_attention(session, client_id)]


@routeur.post(
    "/{client_id}/assistant",
    response_model=ReponseAgentPublique,
    summary="Agent d'intelligence client (F6)",
)
def assistant(
    client_id: int, demande: DemandeAgent, session: SessionRequise, qui: IdentiteRequise
) -> ReponseAgentPublique:
    """Fiche brute, synthèse rédigée, ou question cherchée dans tous les dossiers du client."""
    _client_visible(session, client_id)
    reponse = agent_client.assister(session, qui.utilisateur_id, client_id, demande.demande)
    return ReponseAgentPublique(**asdict(reponse))
