"""Se connecter, et savoir qui l'on est."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.api.schemas import DemandeConnexion, Jeton, UtilisateurPublic
from jurismind.api.securite import IdentiteRequise, authentifier, creer_jeton
from jurismind.db.models import Utilisateur
from jurismind.db.session import get_engine

routeur = APIRouter(tags=["Connexion"])


@routeur.post(
    "/connexion",
    response_model=Jeton,
    summary="Obtenir un jeton",
    responses={401: {"description": "Identifiants refusés"}},
)
def connexion(demande: DemandeConnexion) -> Jeton:
    """Échange un couple adresse / mot de passe contre un jeton signé.

    Un compte importé du vieux logiciel n'a pas de mot de passe utilisable : il existe, mais
    il ne peut pas se connecter tant qu'on ne lui en a pas donné un
    (`python -m jurismind.api.comptes`).
    """
    utilisateur = authentifier(demande.email, demande.mot_de_passe)
    if utilisateur is None:
        # Le même message dans les deux cas : ne pas dire si l'adresse existe.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Adresse ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    jeton, duree = creer_jeton(utilisateur.id, utilisateur.role)
    return Jeton(
        jeton=jeton,
        expire_dans=duree,
        utilisateur=UtilisateurPublic.model_validate(utilisateur, from_attributes=True),
    )


@routeur.get("/moi", response_model=UtilisateurPublic, summary="Le compte du jeton en cours")
def moi(qui: IdentiteRequise) -> UtilisateurPublic:
    with Session(get_engine()) as session:
        utilisateur = session.scalars(select(Utilisateur).where(Utilisateur.id == qui.utilisateur_id)).one()
        return UtilisateurPublic.model_validate(utilisateur, from_attributes=True)
