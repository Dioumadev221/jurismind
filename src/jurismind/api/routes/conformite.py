"""Conflits d'intérêts (bonus, hors offre).

**Ces routes ne prennent pas `SessionRequise`**, contrairement à toutes les autres. Un
contrôle de conflits qui ne verrait que les dossiers du demandeur manquerait précisément ce
qu'il cherche : que le cabinet défend déjà la partie qu'on s'apprête à attaquer. Les
fonctions de `conformite.conflits` ouvrent donc leur propre session, qui voit tout le
cabinet, et ne rendent que le minimum — les références de dossiers ne sont nommées que si le
demandeur y a déjà accès. Chaque appel est inscrit au journal d'audit (voir ADR 0009).
"""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status

from jurismind.api.schemas import ConflitPublic, DemandeConflit, ResultatBalayage
from jurismind.api.securite import IdentiteRequise, refuser_si
from jurismind.conformite.conflits import balayer, conflits_du_dossier, verifier_identite
from jurismind.db.models import Role

routeur = APIRouter(prefix="/conformite", tags=["Conformité"])

RESERVE = "Le contrôle des conflits est un acte professionnel : réservé aux avocats et assistants"


@routeur.post(
    "/verification",
    response_model=list[ConflitPublic],
    summary="Vérifier une identité avant d'ouvrir un dossier",
)
def verification(demande: DemandeConflit, qui: IdentiteRequise) -> list[ConflitPublic]:
    """Le contrôle à faire **avant** d'accepter une affaire.

    Deux niveaux : `certain` quand l'identité ne fait pas de doute (nom identique forme
    comprise, ou coordonnée partagée), `a_verifier` quand la dénomination correspond mais pas
    la forme juridique — deux sociétés distinctes, ou une saisie négligée ? La machine ne
    tranche pas. Une liste vide n'est pas une garantie : elle dit que rien n'a été trouvé
    dans les données du cabinet.
    """
    refuser_si(qui.role is Role.ADMIN, RESERVE)
    conflits = verifier_identite(qui.utilisateur_id, demande.nom, demande.email, demande.telephone)
    return [ConflitPublic(**asdict(conflit)) for conflit in conflits]


@routeur.get(
    "/dossiers/{reference}",
    response_model=list[ConflitPublic],
    summary="Vérifier les parties adverses d'un dossier",
    responses={404: {"description": "Dossier inconnu"}},
)
def du_dossier(reference: str, qui: IdentiteRequise) -> list[ConflitPublic]:
    """Le dossier est cherché dans tout le cabinet : un conflit peut concerner celui d'un autre."""
    refuser_si(qui.role is Role.ADMIN, RESERVE)
    try:
        _, conflits = conflits_du_dossier(qui.utilisateur_id, reference)
    except LookupError as erreur:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(erreur)) from erreur
    return [ConflitPublic(**asdict(conflit)) for conflit in conflits]


@routeur.get(
    "/balayage",
    response_model=list[ResultatBalayage],
    summary="Passer tout le cabinet en revue",
)
def balayage(qui: IdentiteRequise) -> list[ResultatBalayage]:
    """Toutes les parties adverses du cabinet confrontées à la liste de ses clients."""
    refuser_si(qui.role is Role.ADMIN, RESERVE)
    return [
        ResultatBalayage(dossier=reference, conflit=ConflitPublic(**asdict(conflit)))
        for reference, conflit in balayer(qui.utilisateur_id)
    ]
