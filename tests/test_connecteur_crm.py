"""Le connecteur CRM : il encaisse les pannes de l'API et ne se trompe jamais de client."""

from typing import Any, cast

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from jurismind.connectors.crm import (
    ApiCrm,
    CrmIndisponible,
    Rapprochement,
    domaine,
    nom_comparable,
    resoudre_conflits,
    synchroniser_crm,
)
from jurismind.connectors.legacy import Bilan, synchroniser
from jurismind.core.config import get_settings
from jurismind.db.models import Client, ElementCrm, TypeClient, TypeElementCrm
from jurismind.db.session import get_engine
from simulation.crm.app import app

COMPTE: dict[str, Any] = {
    "id": "ACC-00022",
    "name": "Sine Services",
    "type": "company",
    "city": "Thiès",
    "phone": "+221331954096",
    "website": "www.sine-services-sa.example",
    "ninea": "003846949 3A2",
    "lifecycle_stage": "client",
}


def client_de(**champs: Any) -> Client:
    valeurs: dict[str, Any] = {
        "id": champs.pop("id", 1),
        "nom": "SINE SERVICES SA",
        "type": TypeClient.SOCIETE,
        "ville": "Thiès",
        "ninea": "003846949 3A2",
        "telephone": "+221331954096",
        "email": "contact@sine-services-sa.example",
    }
    return Client(**{**valeurs, **champs})


# --------------------------------------------------------------------- normalisation


def test_le_nom_est_comparable_malgre_la_forme_juridique_et_la_casse() -> None:
    assert nom_comparable("SAHEL PÊCHE SA") == nom_comparable("Sahel Pêche") == "sahel peche"


def test_le_domaine_est_extrait_des_emails_et_des_sites() -> None:
    assert domaine("www.sine-services-sa.example") == "sine-services-sa.example"
    assert domaine("Contact@Sine-Services-SA.example") == "sine-services-sa.example"
    assert domaine("  ") is None


# --------------------------------------------------------------------- rapprochement


@pytest.mark.parametrize(
    ("modifications", "indice_attendu"),
    [
        ({}, "ninea"),
        ({"ninea": None}, "téléphone"),
        ({"ninea": None, "phone": None}, "domaine"),
        ({"ninea": None, "phone": None, "website": None}, "dénomination + ville"),
    ],
)
def test_les_indices_sont_essayes_du_plus_fiable_au_moins_fiable(
    modifications: dict[str, Any], indice_attendu: str
) -> None:
    client, indice = Rapprochement([client_de()]).chercher({**COMPTE, **modifications})
    assert client is not None
    assert indice == indice_attendu


def test_une_denomination_partagee_par_deux_villes_ne_suffit_pas() -> None:
    dakarois = client_de(
        id=2, nom="Sine Services SARL", ville="Dakar", ninea=None, telephone=None, email=None
    )
    client, indice = Rapprochement([dakarois]).chercher(
        {**COMPTE, "ninea": None, "phone": None, "website": None}
    )
    assert client is None and indice == "aucun"


def test_une_cle_qui_designe_deux_clients_est_ecartee() -> None:
    jumeaux = [client_de(id=1), client_de(id=2, nom="Sine Services SA", ninea=None, email=None)]
    client, _ = Rapprochement(jumeaux).chercher({**COMPTE, "ninea": None, "website": None})
    assert client is None, "un téléphone partagé par deux fiches ne doit pas servir d'indice"


def test_entre_deux_comptes_le_plus_fiable_gagne() -> None:
    client = client_de()
    prospect = {
        "id": "ACC-00038",
        "name": "Sine Services SARL",
        "city": "Thiès",
        "ninea": None,
        "phone": None,
        "website": None,
    }
    retenus = resoudre_conflits([prospect, COMPTE], Rapprochement([client]), Bilan())
    assert retenus == {"ACC-00022": client}  # le NINEA l'emporte sur la dénomination


def test_a_egalite_aucun_compte_nest_retenu() -> None:
    client = client_de()
    autre = {**COMPTE, "id": "ACC-00099", "name": "Sine Services SA"}
    assert resoudre_conflits([COMPTE, autre], Rapprochement([client]), Bilan()) == {}


# --------------------------------------------------------------------- résistance de l'API


def api_factice(reponses: list[httpx.Response]) -> ApiCrm:
    restantes = list(reponses)

    def repondre(requete: httpx.Request) -> httpx.Response:
        return restantes.pop(0)

    http = httpx.Client(transport=httpx.MockTransport(repondre), base_url="http://crm")
    return ApiCrm(client_http=http, tentatives=4, attente_initiale=0.001)


def page(donnees: list[dict[str, Any]], has_more: bool = False) -> httpx.Response:
    return httpx.Response(200, json={"data": donnees, "has_more": has_more})


def test_une_erreur_passagere_est_reessayee() -> None:
    api = api_factice([httpx.Response(503), httpx.Response(429), page([COMPTE])])
    assert list(api.lister("accounts")) == [COMPTE]


def test_une_api_definitivement_muette_leve_une_erreur_explicite() -> None:
    api = api_factice([httpx.Response(503)] * 4)
    with pytest.raises(CrmIndisponible, match="4 tentatives"):
        api.get("/accounts")


def test_une_cle_dapi_refusee_nest_pas_reessayee() -> None:
    api = api_factice([httpx.Response(401, json={"detail": "clé invalide"})])
    with pytest.raises(httpx.HTTPStatusError):
        api.get("/accounts")  # une seule réponse en réserve : une reprise ferait échouer le test


def test_toutes_les_pages_sont_parcourues() -> None:
    api = api_factice([page([COMPTE], has_more=True), page([{**COMPTE, "id": "ACC-2"}])])
    assert [compte["id"] for compte in api.lister("accounts")] == ["ACC-00022", "ACC-2"]


# --------------------------------------------------------------------- synchronisation complète


def api_du_cabinet() -> ApiCrm:
    """Branche le connecteur sur le CRM factice, sans passer par le réseau."""
    # TestClient hérite de httpx.Client, mais son typage ne l'expose pas.
    http = TestClient(app, headers={"X-API-Key": get_settings().crm_api_key.get_secret_value()})
    return ApiCrm(client_http=cast(httpx.Client, http))


@pytest.fixture
def cabinet_synchronise() -> None:
    tables = (
        "journal_audit, taches, extraits, pieces_jointes, communications, documents, parties, "
        "acces_dossiers, dossiers, contacts, elements_crm, alias_clients, clients, utilisateurs"
    )
    with Session(get_engine()) as session, session.begin():
        session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    synchroniser(cible=get_engine())


@pytest.mark.usefixtures("cabinet_synchronise")
def test_le_crm_enrichit_les_clients_du_cabinet() -> None:
    bilan = synchroniser_crm(api=api_du_cabinet(), cible=get_engine())

    assert bilan.crees["clients_rapproches"] > 20
    assert bilan.crees["activities"] > 0, "les comptes rendus de rendez-vous doivent être importés"

    with Session(get_engine()) as session:
        rapproches = session.scalar(
            select(func.count()).select_from(Client).where(Client.crm_id.is_not(None))
        )
        elements = session.scalars(select(ElementCrm)).all()
    assert rapproches == bilan.crees["clients_rapproches"]
    assert {e.type for e in elements} == set(TypeElementCrm)
    assert all(e.client_id is not None for e in elements)


@pytest.mark.usefixtures("cabinet_synchronise")
def test_la_synchronisation_du_crm_est_rejouable() -> None:
    premier = synchroniser_crm(api=api_du_cabinet(), cible=get_engine())
    second = synchroniser_crm(api=api_du_cabinet(), cible=get_engine())

    assert second.crees.get("clients_rapproches", 0) == 0
    assert second.crees.get("activities", 0) == 0
    assert second.mis_a_jour["activities"] == premier.crees["activities"]
