"""Les dossiers : ce que l'utilisateur en voit, et l'agent d'assistance (F7)."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from jurismind.agents import dossier as agent_dossier
from jurismind.agents.outils import (
    documents_du_dossier,
    dossiers_du_client,
    echanges_du_dossier,
    echeances_a_venir,
    evenements_du_dossier,
    fiche_dossier,
    points_du_dossier,
)
from jurismind.api.schemas import (
    DemandeAgent,
    DocumentPublic,
    DossierPublic,
    EvenementPublic,
    PointAttentionPublic,
    ReponseAgentPublique,
)
from jurismind.api.securite import IdentiteRequise, SessionRequise
from jurismind.db.models import Dossier

routeur = APIRouter(prefix="/dossiers", tags=["Dossiers"])


def _dossier_visible(session: SessionRequise, reference: str) -> Dossier:
    """Le dossier, ou 404. Un dossier qu'on n'a pas le droit de voir **n'existe pas** pour nous."""
    trouve = session.scalars(select(Dossier).where(Dossier.reference == reference)).one_or_none()
    if trouve is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Dossier {reference} introuvable")
    return trouve


@routeur.get("", response_model=list[DossierPublic], summary="Mes dossiers")
def mes_dossiers(session: SessionRequise) -> list[DossierPublic]:
    """Les dossiers auxquels l'utilisateur a accès. La liste est produite par PostgreSQL."""
    clients = {dossier.client_id for dossier in session.scalars(select(Dossier)).all()}
    lignes = [ligne for client_id in clients for ligne in dossiers_du_client(session, client_id)]
    return [DossierPublic.model_validate(ligne) for ligne in sorted(lignes, key=lambda d: d["reference"])]


@routeur.get(
    "/echeances",
    response_model=list[PointAttentionPublic],
    summary="Échéancier : ce qui tombe dans les prochains jours",
)
def echeances(
    session: SessionRequise,
    jours: int = Query(default=30, ge=1, le=365, description="Fenêtre, en jours"),
) -> list[PointAttentionPublic]:
    """Tous dossiers confondus : les délais qui échoient dans la fenêtre demandée.

    C'est la question qu'un avocat se pose chaque matin, et celle à laquelle aucune fiche de
    dossier ne répond : un délai ne se rate pas parce qu'on l'a mal compris, il se rate parce
    qu'on n'a pas rouvert le dossier à temps. Les dates sont reconstituées depuis les actes
    extraits, **relus ou non** — mieux vaut une alerte à vérifier qu'un délai manqué. Le RLS
    fait que chacun ne voit tomber que ses propres dossiers.

    Déclarée **avant** `/{reference}` : FastAPI résout les routes dans l'ordre, et le motif
    variable avalerait `echeances` en le prenant pour une référence de dossier.
    """
    return [PointAttentionPublic(**asdict(point)) for point in echeances_a_venir(session, jours=jours)]


@routeur.get(
    "/{reference}",
    response_model=dict,
    summary="Fiche d'un dossier",
    responses={404: {"description": "Dossier inconnu, ou fermé à cet utilisateur"}},
)
def fiche(reference: str, session: SessionRequise) -> dict:
    """Parties, statut, enjeu, nombre de pièces et d'échanges — tout lu en base."""
    dossier = _dossier_visible(session, reference)
    detail = fiche_dossier(session, dossier.id)
    if detail is None:  # pragma: no cover - déjà écarté par _dossier_visible
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")
    return detail


@routeur.get(
    "/{reference}/chronologie",
    response_model=list[EvenementPublic],
    summary="Chronologie d'un dossier",
)
def chronologie(reference: str, session: SessionRequise) -> list[EvenementPublic]:
    """Construite par le code à partir des dates en base : aucun modèle n'intervient."""
    dossier = _dossier_visible(session, reference)
    return [EvenementPublic(**asdict(evenement)) for evenement in evenements_du_dossier(session, dossier.id)]


@routeur.get("/{reference}/documents", response_model=list[DocumentPublic], summary="Pièces d'un dossier")
def pieces(reference: str, session: SessionRequise) -> list[DocumentPublic]:
    dossier = _dossier_visible(session, reference)
    return [DocumentPublic.model_validate(piece) for piece in documents_du_dossier(session, dossier.id)]


@routeur.get(
    "/{reference}/echanges",
    response_model=list[dict],
    summary="Échanges rattachés à un dossier",
)
def echanges(
    reference: str,
    session: SessionRequise,
    limite: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    """Courriers, courriels et appels de ce dossier, du plus récent au plus ancien."""
    dossier = _dossier_visible(session, reference)
    return echanges_du_dossier(session, dossier.id, limite)


@routeur.get(
    "/{reference}/attention",
    response_model=list[PointAttentionPublic],
    summary="Délais et points d'attention de ce dossier",
)
def attention(reference: str, session: SessionRequise) -> list[PointAttentionPublic]:
    """Les mêmes règles que pour un client, mais resserrées sur un dossier.

    Les règles commerciales (opportunité en sommeil, relance à faire) n'ont pas leur place
    ici : elles parlent du client, pas de l'affaire.
    """
    dossier = _dossier_visible(session, reference)
    return [PointAttentionPublic(**asdict(point)) for point in points_du_dossier(session, dossier.id)]


@routeur.post(
    "/{reference}/assistant",
    response_model=ReponseAgentPublique,
    summary="Agent d'assistance dossier (F7)",
)
def assistant(
    reference: str, demande: DemandeAgent, session: SessionRequise, qui: IdentiteRequise
) -> ReponseAgentPublique:
    """Question précise, synthèse ou chronologie, selon la demande.

    L'intention est devinée par mot-clé quand c'est possible (« chronologie », « résume »),
    sinon par le modèle. Une chronologie revient en moins d'une seconde ; une question ou une
    synthèse demandent 20 à 100 s sur une machine sans GPU.
    """
    dossier = _dossier_visible(session, reference)
    reponse = agent_dossier.assister(session, qui.utilisateur_id, dossier.id, demande.demande)
    return ReponseAgentPublique(**asdict(reponse))
