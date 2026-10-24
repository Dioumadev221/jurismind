"""La démonstration publique : entrer sans mot de passe, et savoir ce qui a été préparé.

Ces routes n'existent que si `DEMO=true`. Hors démonstration elles répondent 404, comme si
elles n'avaient jamais été écrites : un cabinet réel n'a pas de porte sans mot de passe.

L'entrée sans mot de passe ne vaut que pour les comptes du scénario, et ne contourne rien
d'autre : le jeton émis est le même que celui de `/connexion`, et chaque requête qui suit
passe par l'isolation de PostgreSQL. Entrer comme l'avocat B ne montre que ses dossiers.
"""

import json
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.api.schemas import Jeton, UtilisateurPublic
from jurismind.api.securite import creer_jeton
from jurismind.core.config import get_settings
from jurismind.db.models import Utilisateur
from jurismind.db.session import get_engine
from jurismind.demo import SCENARIO

routeur = APIRouter(prefix="/demo", tags=["Démonstration"])


class DemandeEntree(BaseModel):
    email: str = Field(description="Un des comptes listés par `GET /demo`")


@lru_cache
def scenario() -> dict[str, Any]:
    if not SCENARIO.exists():
        return {"comptes": [], "demandes": []}
    return dict(json.loads(SCENARIO.read_text(encoding="utf-8")))


def _exiger_demo() -> None:
    if not get_settings().demo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


@routeur.get("", response_model=dict, summary="Ce que la démonstration propose")
def demo() -> dict[str, Any]:
    """Les comptes ouverts aux visiteurs, le jour du cabinet, et les demandes préparées.

    Une demande préparée a été jouée une fois avec les modèles, sur une machine qui les fait
    tourner. Le serveur public rejoue la réponse du modèle — et seulement elle : recherche,
    contrôles et droits s'exécutent à chaque fois.
    """
    _exiger_demo()
    donnees = scenario()
    return {
        "date_du_cabinet": str(get_settings().date_du_cabinet or donnees.get("date_du_cabinet") or ""),
        "enregistre_le": donnees.get("enregistre_le"),
        "comptes": donnees.get("comptes", []),
        "demandes": [
            {k: demande.get(k) for k in ("nature", "compte", "libelle", "cible", "contexte", "resultat")}
            for demande in donnees.get("demandes", [])
        ],
        "bilan": donnees.get("bilan", {}),
        "contact_url": get_settings().contact_url,
    }


@routeur.post("/connexion", response_model=Jeton, summary="Entrer avec un compte de démonstration")
def entrer(demande: DemandeEntree) -> Jeton:
    _exiger_demo()
    ouverts = {compte["email"] for compte in scenario().get("comptes", [])}
    if demande.email not in ouverts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This account is not open to the demo"
        )
    with Session(get_engine()) as session:
        utilisateur = session.scalars(
            select(Utilisateur).where(Utilisateur.email == demande.email, Utilisateur.actif)
        ).first()
        if utilisateur is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="This account is not open to the demo"
            )
        # Une visite, pas une journée de travail : deux heures suffisent.
        jeton, duree = creer_jeton(utilisateur.id, utilisateur.role, duree_minutes=120)
        return Jeton(
            jeton=jeton,
            expire_dans=duree,
            utilisateur=UtilisateurPublic.model_validate(utilisateur, from_attributes=True),
        )
