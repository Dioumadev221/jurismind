"""CRM factice du cabinet : une API REST qui imite un CRM SaaS.

Comme un vrai CRM, elle exige une clé d'API, pagine ses résultats, permet la
synchronisation incrémentale (`updated_since`) et renvoie parfois des erreurs
429/503 : le connecteur de JurisMind doit savoir les gérer.

Lancement : uv run uvicorn simulation.crm.app:app --port 8100
"""

import json
import os
import random
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

DATA_FILE = Path(os.getenv("CRM_DATA_FILE", "data/crm/crm.json"))
API_KEY = os.getenv("CRM_API_KEY", "crm-dev-key")
ERROR_RATE = float(os.getenv("CRM_ERROR_RATE", "0.05"))
RESSOURCES = ("accounts", "contacts", "opportunities", "activities", "tasks")

app = FastAPI(title="CRM factice – Cabinet Téranga Avocats", version="1.0")
_verrou = threading.Lock()


def _charger() -> dict[str, list[dict[str, Any]]]:
    if not DATA_FILE.exists():
        raise RuntimeError(f"{DATA_FILE} introuvable : lancer d'abord `python -m simulation`.")
    data: dict[str, list[dict[str, Any]]] = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return data


_data = _charger()


def _sauver() -> None:
    DATA_FILE.write_text(json.dumps(_data, ensure_ascii=False, indent=2), encoding="utf-8")


def securite(x_api_key: Annotated[str | None, Header()] = None) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(401, "Clé d'API invalide ou absente (en-tête X-API-Key).")
    tirage = random.random()
    if tirage < ERROR_RATE / 2:
        raise HTTPException(429, "Trop de requêtes, réessayez plus tard.", headers={"Retry-After": "1"})
    if tirage < ERROR_RATE:
        raise HTTPException(503, "Service temporairement indisponible.")


Securise = Depends(securite)


def _page(items: list[dict[str, Any]], page: int, limit: int) -> dict[str, Any]:
    debut = (page - 1) * limit
    return {
        "data": items[debut : debut + limit],
        "page": page,
        "limit": limit,
        "total": len(items),
        "has_more": debut + limit < len(items),
    }


def _lister(
    ressource: str,
    page: int,
    limit: int,
    account_id: str | None,
    updated_since: date | None,
) -> dict[str, Any]:
    items = _data[ressource]
    if account_id:
        items = [i for i in items if i.get("account_id") == account_id]
    if updated_since:
        champ = "updated_at" if ressource == "accounts" else None
        if champ:
            items = [i for i in items if i[champ] >= updated_since.isoformat()]
    return _page(items, page, limit)


Page = Annotated[int, Query(ge=1)]
Limite = Annotated[int, Query(ge=1, le=100)]


@app.get("/accounts", dependencies=[Securise])
def accounts(page: Page = 1, limit: Limite = 20, updated_since: date | None = None) -> dict[str, Any]:
    return _lister("accounts", page, limit, None, updated_since)


@app.get("/accounts/{account_id}", dependencies=[Securise])
def account(account_id: str) -> dict[str, Any]:
    for a in _data["accounts"]:
        if a["id"] == account_id:
            return a
    raise HTTPException(404, "Compte introuvable.")


@app.get("/contacts", dependencies=[Securise])
def contacts(page: Page = 1, limit: Limite = 20, account_id: str | None = None) -> dict[str, Any]:
    return _lister("contacts", page, limit, account_id, None)


@app.get("/opportunities", dependencies=[Securise])
def opportunities(page: Page = 1, limit: Limite = 20, account_id: str | None = None) -> dict[str, Any]:
    return _lister("opportunities", page, limit, account_id, None)


@app.get("/activities", dependencies=[Securise])
def activities(page: Page = 1, limit: Limite = 20, account_id: str | None = None) -> dict[str, Any]:
    return _lister("activities", page, limit, account_id, None)


@app.get("/tasks", dependencies=[Securise])
def tasks(page: Page = 1, limit: Limite = 20, account_id: str | None = None) -> dict[str, Any]:
    return _lister("tasks", page, limit, account_id, None)


class NouvelleTache(BaseModel):
    account_id: str
    title: str
    due_date: date
    owner: str


class NouvelleNote(BaseModel):
    account_id: str
    subject: str
    note: str
    owner: str


def _creer(ressource: str, prefixe: str, valeurs: dict[str, Any]) -> dict[str, Any]:
    if not any(a["id"] == valeurs["account_id"] for a in _data["accounts"]):
        raise HTTPException(422, "account_id inconnu.")
    with _verrou:
        item = {"id": f"{prefixe}-{len(_data[ressource]) + 1:05d}", **valeurs}
        _data[ressource].append(item)
        _sauver()
    return item


@app.post("/tasks", status_code=201, dependencies=[Securise])
def creer_tache(t: NouvelleTache) -> dict[str, Any]:
    return _creer("tasks", "TSK", {**t.model_dump(mode="json"), "status": "ouverte"})


@app.post("/activities", status_code=201, dependencies=[Securise])
def creer_note(n: NouvelleNote) -> dict[str, Any]:
    return _creer(
        "activities",
        "ACT",
        {**n.model_dump(), "type": "note", "date": datetime.now(UTC).isoformat()},
    )
