"""La démonstration publique : rejouer le modèle sans tricher sur le reste.

Ce qui est vérifié ici, c'est ce qui rendrait la démonstration malhonnête ou fragile :
une réponse rejouée qui ne serait pas celle du modèle, une question imprévue qui ferait
planter l'API, une base restaurée dont le rôle de l'application aurait perdu ses droits —
ou gardé trop de droits —, une porte sans mot de passe ouverte hors démonstration.
"""

from __future__ import annotations

import gzip
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from jurismind.api.main import app
from jurismind.api.securite import creer_jeton
from jurismind.core.config import Settings, get_settings
from jurismind.db.models import Role
from jurismind.db.session import session_utilisateur
from jurismind.demo import base
from jurismind.llm.rejeu import (
    ChatEnregistre,
    ChatRejoue,
    ModeleIndisponible,
    Registre,
    VecteursEnregistres,
    VecteursRejoues,
    charger,
)
from jurismind.retrieval import Filtres, rechercher
from tests.conftest import Cabinet

DIMENSION = 1024


class VecteursFixes:
    def embed_query(self, _: str) -> list[float]:
        return [1.0] + [0.0] * (DIMENSION - 1)

    def embed_documents(self, textes: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in textes]


@pytest.fixture
def registre(tmp_path: Path) -> Iterator[Path]:
    chemin = tmp_path / "enregistrements.jsonl"
    yield chemin
    charger.cache_clear()


# ------------------------------------------------------------------------------ rejeu


def test_une_reponse_enregistree_est_rejouee_a_lidentique(registre: Path) -> None:
    vrai = FakeListChatModel(responses=['{"reponse": "8 jours", "sources": [1]}'])
    enregistre = ChatEnregistre(interne=vrai, registre=Registre(registre), json_impose=True)
    assert enregistre.invoke("Quel délai ?").content == '{"reponse": "8 jours", "sources": [1]}'

    rejoue = ChatRejoue(chemin=str(registre), json_impose=True)
    assert rejoue.invoke("Quel délai ?").content == '{"reponse": "8 jours", "sources": [1]}'


def test_une_invite_jamais_vue_na_pas_de_reponse(registre: Path) -> None:
    ChatEnregistre(interne=FakeListChatModel(responses=["oui"]), registre=Registre(registre)).invoke(
        "Question A"
    )
    with pytest.raises(ModeleIndisponible):
        ChatRejoue(chemin=str(registre)).invoke("Question A ")  # un espace de plus : autre invite


def test_le_mode_json_fait_partie_de_la_cle(registre: Path) -> None:
    """Une même invite, avec et sans sortie JSON imposée, n'appelle pas la même réponse."""
    ChatEnregistre(
        interne=FakeListChatModel(responses=["{}"]), registre=Registre(registre), json_impose=True
    ).invoke("Invite")
    with pytest.raises(ModeleIndisponible):
        ChatRejoue(chemin=str(registre), json_impose=False).invoke("Invite")


def test_les_vecteurs_des_questions_sont_rejoues(registre: Path) -> None:
    VecteursEnregistres(VecteursFixes(), Registre(registre)).embed_query("opposition")  # type: ignore[arg-type]
    assert VecteursRejoues(str(registre)).embed_query("opposition")[0] == 1.0
    with pytest.raises(ModeleIndisponible):
        VecteursRejoues(str(registre)).embed_query("autre chose")


def test_la_cle_ne_garde_pas_les_vecteurs_des_pieces(registre: Path) -> None:
    """Ceux-là sont déjà en base : les consigner doublerait l'export pour rien."""
    VecteursEnregistres(VecteursFixes(), Registre(registre)).embed_documents(["a", "b"])  # type: ignore[arg-type]
    assert not registre.exists() or registre.read_text() == ""


# ---------------------------------------------------- une question imprévue, sans modèle


def test_sans_vecteur_la_recherche_passe_par_les_mots(
    cabinet: Cabinet, monkeypatch: pytest.MonkeyPatch, registre: Path
) -> None:
    monkeypatch.setattr(
        "jurismind.retrieval.recherche.modele_embeddings", lambda: VecteursRejoues(str(registre))
    )
    with session_utilisateur(cabinet.fall) as session:
        resultats = rechercher(session, "tribunal condamne", Filtres())
    assert resultats and resultats[0].rang_vectoriel is None


def test_une_demande_sans_modele_repond_503_avec_une_phrase(
    cabinet: Cabinet, monkeypatch: pytest.MonkeyPatch, registre: Path
) -> None:
    monkeypatch.setattr(
        "jurismind.retrieval.recherche.modele_embeddings", lambda: VecteursRejoues(str(registre))
    )
    monkeypatch.setattr(
        "jurismind.rag.reponse.modele_chat",
        lambda *a, **k: ChatRejoue(chemin=str(registre), json_impose=True),
    )
    api = cast(httpx.Client, TestClient(app))
    jeton, _ = creer_jeton(cabinet.fall, Role.AVOCAT)
    reponse = api.post(
        "/questions",
        json={"question": "tribunal condamne", "filtres": {}},
        headers={"Authorization": f"Bearer {jeton}"},
    )
    assert reponse.status_code == 503
    assert "Démonstration publique" in reponse.json()["detail"]


# --------------------------------------------------------------- l'entrée de démonstration


def test_hors_demonstration_lentree_sans_mot_de_passe_nexiste_pas() -> None:
    api = cast(httpx.Client, TestClient(app))
    assert api.get("/demo").status_code == 404
    assert api.post("/demo/connexion", json={"email": "m.dieng@test"}).status_code == 404


def test_en_demonstration_seuls_les_comptes_du_scenario_entrent(
    cabinet: Cabinet, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jurismind.api.routes import demo

    monkeypatch.setattr(get_settings(), "demo", True)
    monkeypatch.setattr(demo, "scenario", lambda: {"comptes": [{"email": "a.fall@test"}], "demandes": []})
    api = cast(httpx.Client, TestClient(app))

    assert api.post("/demo/connexion", json={"email": "m.dieng@test"}).status_code == 403
    entree = api.post("/demo/connexion", json={"email": "a.fall@test"})
    assert entree.status_code == 200
    # Le jeton émis passe par l'isolation comme n'importe quel autre : Me Fall ne voit que D2026-0027.
    dossiers = api.get("/dossiers", headers={"Authorization": f"Bearer {entree.json()['jeton']}"}).json()
    assert [d["reference"] for d in dossiers] == ["D2026-0027"]


def test_en_demonstration_la_racine_presente_le_produit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "demo", True)
    page = cast(httpx.Client, TestClient(app)).get("/", follow_redirects=False)
    assert page.status_code == 200 and "cite ses sources" in page.text


# ------------------------------------------------------------------- réglages hébergés


def test_une_chaine_unique_donne_les_deux_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    reglages = Settings(
        DATABASE_URL="postgresql://proprio:secret@ep-1.neon.tech/neondb?sslmode=require",
        postgres_app_password=SecretStr("appli"),
    )
    assert (
        reglages.database_url == "postgresql+psycopg://proprio:secret@ep-1.neon.tech/neondb?sslmode=require"
    )
    application = make_url(reglages.app_database_url)
    assert (application.username, application.password, application.host) == (
        "jurismind_app",
        "appli",
        "ep-1.neon.tech",
    )
    assert application.database == "neondb" and application.query["sslmode"] == "require"


# --------------------------------------------------------------- export et restauration


@pytest.fixture
def base_vierge() -> Iterator[str]:
    """Une base neuve, détruite après le test : la cible d'une restauration."""
    nom = f"jurismind_restaure_{uuid.uuid4().hex[:8]}"
    serveur = create_engine(
        get_settings().database_url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT"
    )
    with serveur.connect() as connexion:
        connexion.execute(text(f'CREATE DATABASE "{nom}"'))
    dsn = make_url(get_settings().database_url).set(drivername="postgresql", database=nom)
    yield dsn.render_as_string(hide_password=False)
    with serveur.connect() as connexion:
        connexion.execute(text(f'DROP DATABASE "{nom}" WITH (FORCE)'))
    serveur.dispose()


@pytest.mark.skipif(not __import__("shutil").which("pg_dump"), reason="pg_dump absent")
def test_lexport_restaure_garde_lisolation(cabinet: Cabinet, base_vierge: str, tmp_path: Path) -> None:
    export = base.exporter(
        tmp_path / "base.sql.gz",
        dsn=make_url(get_settings().database_url)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False),
    )
    with gzip.open(export, "rt") as fichier:
        assert fichier.read(200)

    base.restaurer(export, dsn=base_vierge)
    assert base.base_chargee(base_vierge)

    # Le rôle de l'application lit la base restaurée… sous l'isolation, et seulement sous elle.
    reglages = get_settings()
    application = make_url(base_vierge).set(
        username=reglages.postgres_app_user, password=reglages.postgres_app_password.get_secret_value()
    )
    with psycopg.connect(application.render_as_string(hide_password=False)) as connexion:
        connexion.execute("SELECT set_config('app.utilisateur_id', %s, true)", (str(cabinet.fall),))
        references = [r[0] for r in connexion.execute("SELECT reference FROM dossiers ORDER BY 1")]
        assert references == ["D2026-0027"]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connexion.execute("DELETE FROM journal_audit")


@pytest.mark.skipif(not __import__("shutil").which("pg_dump"), reason="pg_dump absent")
def test_la_remise_a_zero_efface_les_decisions_des_visiteurs(
    cabinet: Cabinet, base_vierge: str, tmp_path: Path
) -> None:
    dsn = (
        make_url(get_settings().database_url)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    base.restaurer(base.exporter(tmp_path / "base.sql.gz", dsn=dsn), dsn=base_vierge)

    with psycopg.connect(base_vierge) as connexion:
        email = connexion.execute("SELECT id FROM communications WHERE dossier_id IS NULL").fetchone()
        assert email is not None
        dossier = connexion.execute("SELECT id FROM dossiers LIMIT 1").fetchone()
        assert dossier is not None
        connexion.execute("UPDATE communications SET dossier_id = %s WHERE id = %s", (dossier[0], email[0]))
        connexion.execute(
            "INSERT INTO journal_audit (utilisateur_id, action, details, cree_le) "
            "SELECT %s, 'visite', '{}'::jsonb, now()",
            (cabinet.fall,),
        )

    base.reinitialiser(base_vierge)

    with psycopg.connect(base_vierge) as connexion:
        assert connexion.execute(
            "SELECT dossier_id FROM communications WHERE id = %s", (email[0],)
        ).fetchone() == (None,)
        assert connexion.execute("SELECT count(*) FROM journal_audit WHERE action = 'visite'").fetchone() == (
            0,
        )


def test_le_scenario_est_lisible_par_lapi(tmp_path: Path) -> None:
    """Le format écrit par `enregistrer` est celui que `/demo` relit."""
    import jurismind.demo.scenario as module
    from jurismind.demo.scenario import Compte, Demande, ecrire

    module_scenario = module.SCENARIO
    try:
        module.SCENARIO = tmp_path / "scenario.json"
        ecrire(
            [Compte("a@x", "Me A", "avocat", 3, "Avocat")],
            [Demande("question", "a@x", "Q ?", {"question": "Q ?", "filtres": {}}, resultat={"juste": True})],
            "2026-09-19",
        )
        donnees = json.loads(module.SCENARIO.read_text())
    finally:
        module.SCENARIO = module_scenario
    assert donnees["bilan"] == {"questions": 1, "justes": 1}
    assert donnees["comptes"][0]["email"] == "a@x"
