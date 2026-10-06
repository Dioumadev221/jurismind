"""L'API REST de JurisMind (F10).

    uv run uvicorn jurismind.api.main:app --reload --port 8000

Documentation interactive sur http://localhost:8000/docs.

Deux principes tiennent toute la surface :

- **aucune route ne se connecte avec la clé propriétaire.** Chaque requête authentifiée ouvre
  une session au nom de l'utilisateur du jeton, donc soumise au RLS de PostgreSQL. Un dossier
  qu'on n'a pas le droit de voir répond 404, pas 403 : on ne révèle pas son existence.
- **aucune route ne produit d'effet sans un oui humain.** Les agents déposent des propositions ;
  `POST /propositions/{id}/validation` est le seul endroit où quelque chose se produit.
"""

import logging
from typing import Any

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from jurismind.api.routes import clients, connexion, courrier, documents, dossiers, recherche
from jurismind.api.schemas import Sante
from jurismind.core.config import get_settings
from jurismind.db.session import get_engine

logger = logging.getLogger(__name__)

DESCRIPTION = """
API du cabinet : recherche dans les pièces, réponses citées, et quatre agents.

**Ce qui est garanti.** Les droits sont appliqués par PostgreSQL (Row-Level Security) et non
par le code des routes : un endpoint mal écrit ne peut pas faire fuiter le dossier d'un autre
client. Les réponses ne citent que des sources réellement utilisées, vérifiées par le code, et
s'abstiennent quand les pièces ne permettent pas de conclure.

**Ce qu'il faut savoir avant d'appeler.** Les routes qui font appel à un modèle local
(`/questions`, `/*/assistant`, `/documents/{id}/analyse`, `/courrier/tri`) demandent de 20 à
100 secondes sur une machine sans GPU. Celles qui ne lisent que la base
(`/*/chronologie`, `/clients/{id}/attention`, `/propositions`) répondent immédiatement.

**Fonctionnalités couvertes** : F2 et F11 (`/questions`), F3 (`/recherche`),
F4 et F5 (`/documents`), F6 (`/clients/{id}/assistant`), F7 (`/dossiers/{ref}/assistant`),
F8 (`/documents/{id}/analyse`), F9 (`/courrier/tri` et `/propositions`), F12 (partout).
"""

ETIQUETTES: list[dict[str, Any]] = [
    {"name": "Connexion", "description": "Obtenir un jeton et savoir qui l'on est."},
    {"name": "Recherche", "description": "Recherche hybride et réponses citées."},
    {"name": "Dossiers", "description": "Fiche, chronologie, pièces, agent d'assistance."},
    {"name": "Clients", "description": "Fiche, points d'attention, agent d'intelligence client."},
    {"name": "Documents", "description": "Fiche, texte lu, valeurs extraites, agent d'analyse."},
    {
        "name": "Courrier et décisions",
        "description": "Tri du courrier entrant, et file des propositions à valider ou rejeter.",
    },
    {"name": "Technique", "description": "État du service."},
]

app = FastAPI(
    title="JurisMind",
    version="0.1.0",
    summary="Recherche, réponses citées et agents pour un cabinet d'avocats",
    description=DESCRIPTION,
    openapi_tags=ETIQUETTES,
    contact={"name": "JurisMind"},
    license_info={"name": "MIT"},
)

for routeur in (
    connexion.routeur,
    recherche.routeur,
    dossiers.routeur,
    clients.routeur,
    documents.routeur,
    courrier.routeur,
):
    app.include_router(routeur)


@app.get("/sante", response_model=Sante, tags=["Technique"], summary="État du service")
def sante() -> Sante:
    """Vérifie que la base répond. Volontairement ouverte : un contrôle de santé n'a pas de jeton."""
    base = True
    try:
        with Session(get_engine()) as session:
            session.execute(text("SELECT 1"))
    except Exception as erreur:  # noqa: BLE001 - on veut rendre « dégradé », pas une trace
        logger.warning("Base injoignable : %s", erreur)
        base = False
    return Sante(
        statut="ok" if base else "dégradé",
        base=base,
        modeles=get_settings().llm_fournisseur,
    )
