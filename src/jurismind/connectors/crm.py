"""Connecteur vers le CRM du cabinet.

Deux difficultés, très différentes de celles du logiciel de gestion :

1. **L'API n'est pas fiable** : elle pagine, exige une clé, et renvoie parfois 429 (trop de
   requêtes) ou 503 (indisponible). Le connecteur réessaie avec une attente croissante.
2. **Le CRM ne parle pas le même langage que le cabinet** : « Sahel Pêche » côté CRM,
   « SAHEL PÊCHE SA » côté logiciel de gestion. Il faut rapprocher les deux sans se tromper
   de client, faute de quoi on donnerait à l'un les informations de l'autre.

Usage : uv run python -m jurismind.connectors --crm
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import suppress
from datetime import date
from typing import Any, Self

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from jurismind.connectors.legacy import Bilan, normaliser, telephone, texte
from jurismind.core.config import get_settings
from jurismind.db.models import Client, ElementCrm, TypeElementCrm
from jurismind.db.session import get_engine

logger = logging.getLogger(__name__)

CODES_A_REESSAYER = {429, 500, 502, 503, 504}
FORMES_JURIDIQUES = {"sarl", "suarl", "sa", "sas", "gie", "sci"}


class CrmIndisponible(RuntimeError):
    """Le CRM n'a pas répondu, même après plusieurs tentatives."""


class ApiCrm:
    """Accès HTTP au CRM : clé d'API, pagination, et reprise après erreur."""

    def __init__(
        self,
        client_http: httpx.Client | None = None,
        tentatives: int = 4,
        attente_initiale: float = 0.5,
    ) -> None:
        reglages = get_settings()
        self.tentatives = tentatives
        self.attente_initiale = attente_initiale
        self.http = client_http or httpx.Client(
            base_url=reglages.crm_base_url,
            headers={"X-API-Key": reglages.crm_api_key.get_secret_value()},
            timeout=10.0,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exception: object) -> None:
        self.http.close()

    def _attendre(self, essai: int, reponse: httpx.Response | None) -> None:
        """Attente croissante, en respectant l'en-tête `Retry-After` si le CRM en envoie un."""
        if reponse is not None and (retry_after := reponse.headers.get("Retry-After")):
            with suppress(ValueError):  # un « Retry-After » illisible ne doit pas tout arrêter
                time.sleep(min(float(retry_after), 10.0))
                return
        # Exponentielle avec un peu de hasard, pour ne pas taper toutes en même temps.
        time.sleep(self.attente_initiale * (2**essai) * (1 + random.random() / 2))

    def get(self, chemin: str, **parametres: Any) -> dict[str, Any]:
        derniere_erreur: Exception | None = None
        for essai in range(self.tentatives):
            reponse = None
            try:
                reponse = self.http.get(chemin, params=parametres)
                if reponse.status_code in CODES_A_REESSAYER:
                    raise httpx.HTTPStatusError(
                        f"{reponse.status_code} sur {chemin}", request=reponse.request, response=reponse
                    )
                reponse.raise_for_status()
                donnees: dict[str, Any] = reponse.json()
                return donnees
            except (httpx.HTTPStatusError, httpx.TransportError) as erreur:
                derniere_erreur = erreur
                statut = getattr(getattr(erreur, "response", None), "status_code", None)
                if statut is not None and statut not in CODES_A_REESSAYER:
                    raise  # 401, 404… : réessayer n'y changerait rien
                logger.warning("CRM %s : tentative %s/%s (%s)", chemin, essai + 1, self.tentatives, erreur)
                if essai < self.tentatives - 1:
                    self._attendre(essai, reponse)
        raise CrmIndisponible(f"{chemin} : {self.tentatives} tentatives sans succès") from derniere_erreur

    def lister(self, ressource: str, taille_page: int = 100) -> Iterator[dict[str, Any]]:
        """Parcourt toutes les pages d'une ressource du CRM."""
        page = 1
        while True:
            reponse = self.get(f"/{ressource}", page=page, limit=taille_page)
            yield from reponse["data"]
            if not reponse.get("has_more"):
                return
            page += 1


# --------------------------------------------------------------------------- rapprochement


def nom_comparable(nom: str) -> str:
    """Nom sans accents, sans ponctuation ni forme juridique : « SAHEL PÊCHE SA » → « sahel peche »."""
    return " ".join(mot for mot in normaliser(nom).split() if mot not in FORMES_JURIDIQUES)


def domaine(valeur: str | None) -> str | None:
    """Domaine d'un email ou d'un site : « www.sine-services.example » → « sine-services.example »."""
    brut = texte(valeur)
    if not brut:
        return None
    brut = brut.lower().split("@")[-1]
    for prefixe in ("https://", "http://", "www."):
        brut = brut.removeprefix(prefixe)
    return brut.strip("/") or None


# Indices de rapprochement, du plus fiable au moins fiable.
INDICES = ("ninea", "téléphone", "domaine", "dénomination + ville")


class Rapprochement:
    """Retrouve à quel client du cabinet correspond un compte du CRM.

    Quatre indices, du plus sûr au moins sûr : NINEA (identifiant fiscal), téléphone,
    domaine du site ou de l'email, puis dénomination **et** ville. Un indice qui désigne
    plusieurs clients est écarté : on préfère ne pas rapprocher plutôt que se tromper de
    client, car un faux rapprochement donnerait à un tiers les informations d'un client.
    """

    def __init__(self, clients: Sequence[Client]) -> None:
        self.index = {
            "ninea": self._index(clients, lambda c: normaliser(c.ninea or "") or None),
            "téléphone": self._index(clients, lambda c: c.telephone),
            "domaine": self._index(clients, lambda c: domaine(c.email)),
            "dénomination + ville": self._index(clients, self._nom_et_ville),
        }

    @staticmethod
    def _nom_et_ville(client: Client) -> str | None:
        nom = nom_comparable(client.nom)
        return f"{nom}|{normaliser(client.ville or '')}" if nom else None

    @staticmethod
    def _index(clients: Sequence[Client], cle: Any) -> dict[str, Client | None]:
        """`None` marque une clé ambiguë (plusieurs clients) : elle ne servira pas."""
        index: dict[str, Client | None] = {}
        for client in clients:
            valeur = cle(client)
            if valeur:
                index[valeur] = None if valeur in index else client
        return index

    @staticmethod
    def _valeurs(compte: Mapping[str, Any]) -> dict[str, str | None]:
        nom = nom_comparable(str(compte.get("name") or ""))
        return {
            "ninea": normaliser(str(compte.get("ninea") or "")) or None,
            "téléphone": telephone(compte.get("phone")),
            "domaine": domaine(compte.get("website")),
            "dénomination + ville": f"{nom}|{normaliser(str(compte.get('city') or ''))}" if nom else None,
        }

    def chercher(self, compte: Mapping[str, Any]) -> tuple[Client | None, str]:
        """Renvoie le client trouvé et l'indice utilisé (les indices sont essayés par fiabilité)."""
        valeurs = self._valeurs(compte)
        for indice in INDICES:
            valeur = valeurs[indice]
            if valeur and (client := self.index[indice].get(valeur)) is not None:
                return client, indice
        return None, "aucun"


# --------------------------------------------------------------------------- conversions


def _date(valeur: Any) -> date | None:
    brut = texte(valeur)
    return date.fromisoformat(brut[:10]) if brut else None


def convertir_opportunite(ligne: Mapping[str, Any], client_id: int) -> ElementCrm:
    return ElementCrm(
        external_id=str(ligne["id"]),
        client_id=client_id,
        type=TypeElementCrm.OPPORTUNITE,
        titre=texte(ligne.get("name"), 300) or "Opportunité",
        date_element=_date(ligne.get("close_date")),
        montant_fcfa=int(ligne["amount"]) if ligne.get("amount") is not None else None,
        statut=texte(ligne.get("stage"), 40),
        responsable=texte(ligne.get("owner"), 255),
        donnees=dict(ligne),
    )


def convertir_activite(ligne: Mapping[str, Any], client_id: int) -> ElementCrm:
    return ElementCrm(
        external_id=str(ligne["id"]),
        client_id=client_id,
        type=TypeElementCrm.ACTIVITE,
        titre=texte(ligne.get("subject"), 300) or "Échange",
        contenu=texte(ligne.get("note")),
        date_element=_date(ligne.get("date")),
        statut=texte(ligne.get("type"), 40),
        responsable=texte(ligne.get("owner"), 255),
        donnees=dict(ligne),
    )


def convertir_tache(ligne: Mapping[str, Any], client_id: int) -> ElementCrm:
    return ElementCrm(
        external_id=str(ligne["id"]),
        client_id=client_id,
        type=TypeElementCrm.TACHE,
        titre=texte(ligne.get("title"), 300) or "Tâche",
        date_element=_date(ligne.get("due_date")),
        statut=texte(ligne.get("status"), 40),
        responsable=texte(ligne.get("owner"), 255),
        donnees=dict(ligne),
    )


CONVERSIONS = {
    "opportunities": convertir_opportunite,
    "activities": convertir_activite,
    "tasks": convertir_tache,
}


def resoudre_conflits(
    comptes: Sequence[Mapping[str, Any]], rapprochement: Rapprochement, bilan: Bilan
) -> dict[str, Client]:
    """Attribue au plus un compte CRM par client, et un seul client par compte.

    Deux comptes peuvent viser le même client : par exemple le prospect « Casamance Services
    SARL » et le client « Casamance Services SA ». C'est l'indice le plus fiable qui l'emporte
    (NINEA > téléphone > domaine > dénomination). À égalité, aucun des deux n'est retenu :
    mieux vaut un client non enrichi qu'un client enrichi avec les informations d'un autre.
    """
    retenus: dict[int, tuple[str, Client, int]] = {}  # client -> (compte, client, force)
    ambigus: set[int] = set()

    for compte in comptes:
        identifiant = str(compte["id"])
        client, indice = rapprochement.chercher(compte)
        if client is None:
            logger.info("Compte CRM sans correspondance : %s", compte.get("name"))
            bilan.ignorer("comptes_crm")
            continue

        force = len(INDICES) - INDICES.index(indice)
        precedent = retenus.get(client.id)
        if precedent is None:
            retenus[client.id] = (identifiant, client, force)
            logger.debug("%s ← %s (par %s)", client.nom, compte.get("name"), indice)
        elif force > precedent[2]:
            logger.info("Compte CRM %s écarté : un indice plus fiable désigne %s", precedent[0], client.nom)
            bilan.ignorer("comptes_crm")
            retenus[client.id] = (identifiant, client, force)
        elif force == precedent[2]:
            logger.warning(
                "Rapprochement ambigu pour %s (%s et %s) : aucun compte retenu",
                client.nom,
                precedent[0],
                identifiant,
            )
            ambigus.add(client.id)
        else:
            logger.info("Compte CRM %s écarté au profit de %s", identifiant, precedent[0])
            bilan.ignorer("comptes_crm")

    for client_id in ambigus:
        retenus.pop(client_id, None)
        bilan.ignorer("comptes_crm")
        bilan.ignorer("comptes_crm")  # les deux comptes en conflit sont écartés

    return {identifiant: client for identifiant, client, _ in retenus.values()}


# --------------------------------------------------------------------------- synchronisation


def synchroniser_crm(api: ApiCrm | None = None, cible: Any = None) -> Bilan:
    """Rapproche les comptes du CRM de nos clients, puis importe ce qui les concerne."""
    bilan = Bilan()
    ferme_api = api is None
    api = api or ApiCrm()
    try:
        comptes = list(api.lister("accounts"))
        with Session(cible or get_engine()) as session, session.begin():
            clients = list(session.scalars(select(Client)))
            rapprochement = Rapprochement(clients)

            par_compte = resoudre_conflits(comptes, rapprochement, bilan)
            for identifiant, client in par_compte.items():
                if client.crm_id != identifiant:
                    client.crm_id = identifiant
                    bilan.compter("clients_rapproches", cree=True)

            existants = {element.external_id: element for element in session.scalars(select(ElementCrm))}
            for ressource, convertir in CONVERSIONS.items():
                for ligne in api.lister(ressource):
                    proprietaire = par_compte.get(str(ligne.get("account_id")))
                    if proprietaire is None:
                        # Élément d'un compte non rapproché (prospect) : sans client, il n'a
                        # pas de place dans JurisMind, où tout est rattaché à un client.
                        bilan.ignorer(ressource)
                        continue
                    nouveau = convertir(ligne, proprietaire.id)
                    ancien = existants.get(nouveau.external_id)
                    if ancien is None:
                        session.add(nouveau)
                        existants[nouveau.external_id] = nouveau
                        bilan.compter(ressource, cree=True)
                    else:
                        for champ in (
                            "titre",
                            "contenu",
                            "date_element",
                            "montant_fcfa",
                            "statut",
                            "responsable",
                            "donnees",
                            "client_id",
                        ):
                            setattr(ancien, champ, getattr(nouveau, champ))
                        bilan.compter(ressource, cree=False)
    finally:
        if ferme_api:
            api.http.close()
    return bilan
