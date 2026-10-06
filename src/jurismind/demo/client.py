"""Accès à l'API depuis la démo.

La démo ne touche **jamais** la base : elle passe par l'API, avec le jeton de l'utilisateur
connecté. C'est le seul moyen de montrer que l'isolation tient pour de bon — si la démo
lisait PostgreSQL avec la clé propriétaire, elle afficherait tout, et ne prouverait rien.
"""

from __future__ import annotations

from typing import Any

import httpx

# Les appels aux agents durent de 20 à 100 s sur une machine sans GPU.
DELAI = 300.0


class ApiIndisponible(RuntimeError):
    """L'API ne répond pas : il faut la démarrer avant la démo."""


class ApiRefuse(RuntimeError):
    """L'API a répondu une erreur métier (introuvable, déjà tranché, droits insuffisants)."""

    def __init__(self, code: int, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class Api:
    """Appels à l'API de JurisMind, avec ou sans jeton."""

    def __init__(self, base_url: str, jeton: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.jeton = jeton

    def _entetes(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.jeton}"} if self.jeton else {}

    def _appeler(self, methode: str, chemin: str, **options: Any) -> Any:
        try:
            with httpx.Client(base_url=self.base_url, timeout=DELAI) as client:
                reponse = client.request(methode, chemin, headers=self._entetes(), **options)
        except httpx.TransportError as erreur:
            raise ApiIndisponible(f"{self.base_url} ne répond pas") from erreur
        if reponse.status_code >= 400:
            detail = "Erreur inattendue"
            try:
                detail = str(reponse.json().get("detail", detail))
            except ValueError:
                pass
            raise ApiRefuse(reponse.status_code, detail)
        return reponse.json()

    def get(self, chemin: str, **parametres: Any) -> Any:
        return self._appeler("GET", chemin, params=parametres or None)

    def post(self, chemin: str, corps: dict[str, Any] | None = None) -> Any:
        return self._appeler("POST", chemin, json=corps or {})

    # ------------------------------------------------------------------ raccourcis

    def connexion(self, email: str, mot_de_passe: str) -> dict[str, Any]:
        donnees: dict[str, Any] = self.post("/connexion", {"email": email, "mot_de_passe": mot_de_passe})
        return donnees

    def sante(self) -> dict[str, Any]:
        donnees: dict[str, Any] = self.get("/sante")
        return donnees
