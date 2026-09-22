"""Préparation des tests : une base dédiée, et un mini-cabinet de test."""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from jurismind.core.config import get_settings
from jurismind.db.models import (
    AccesDossier,
    Canal,
    Client,
    Communication,
    Document,
    Dossier,
    Extrait,
    Role,
    SensEchange,
    StatutDossier,
    TypeClient,
    TypeDossier,
    Utilisateur,
)
from jurismind.db.session import get_engine

BASE_DE_TEST = "jurismind_test"
TABLES = (
    "extraits, pieces_jointes, communications, documents, parties, "
    "acces_dossiers, dossiers, contacts, clients, utilisateurs"
)


def pytest_configure(config: pytest.Config) -> None:
    """Les tests utilisent leur propre base, jamais celle de développement."""
    os.environ["POSTGRES_DB"] = BASE_DE_TEST


@pytest.fixture(scope="session", autouse=True)
def base_de_test() -> None:
    """Crée la base de test si besoin, puis y applique toutes les migrations."""
    adresse_serveur = get_settings().database_url.rsplit("/", 1)[0] + "/postgres"
    serveur = create_engine(adresse_serveur, isolation_level="AUTOCOMMIT")
    with serveur.connect() as connexion:
        existe = connexion.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :nom"), {"nom": BASE_DE_TEST}
        ).scalar()
        if not existe:
            connexion.execute(text(f'CREATE DATABASE "{BASE_DE_TEST}"'))
    serveur.dispose()
    command.upgrade(Config("alembic.ini"), "head")


@dataclass
class Cabinet:
    """Les identifiants des personnes du mini-cabinet."""

    dieng: int  # avocat : dossiers D2026-0024 et D2026-0025
    fall: int  # avocate : dossier D2026-0027
    sy: int  # assistante : dossier D2026-0024 seulement
    admin: int  # administrateur : aucun dossier


def _dossier(reference: str, client: Client) -> Dossier:
    return Dossier(
        reference=reference,
        client=client,
        intitule=f"Dossier {reference}",
        type=TypeDossier.CONTENTIEUX,
        matiere="RECOUV",
        statut=StatutDossier.EN_COURS,
        date_ouverture=date(2026, 8, 9),
    )


@pytest.fixture
def cabinet() -> Iterator[Cabinet]:
    """Vide la base de test puis y crée un mini-cabinet (avec la clé propriétaire)."""
    with Session(get_engine()) as s, s.begin():
        s.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))

        dieng = Utilisateur(
            email="m.dieng@test", nom_complet="Me Dieng", mot_de_passe_hash="x", role=Role.AVOCAT
        )
        fall = Utilisateur(
            email="a.fall@test", nom_complet="Me Fall", mot_de_passe_hash="x", role=Role.AVOCAT
        )
        sy = Utilisateur(
            email="c.sy@test", nom_complet="Coumba Sy", mot_de_passe_hash="x", role=Role.ASSISTANT
        )
        admin = Utilisateur(email="admin@test", nom_complet="Admin", mot_de_passe_hash="x", role=Role.ADMIN)

        sine = Client(nom="Sine Services SA", type=TypeClient.SOCIETE)
        dakar = Client(nom="Dakar Télécom SARL", type=TypeClient.SOCIETE)
        d24 = _dossier("D2026-0024", sine)
        d25 = _dossier("D2026-0025", sine)
        d27 = _dossier("D2026-0027", dakar)
        s.add_all([dieng, fall, sy, admin, d24, d25, d27])
        s.flush()

        s.add_all(
            [
                AccesDossier(dossier=d24, utilisateur=dieng, est_responsable=True),
                AccesDossier(dossier=d24, utilisateur=sy),
                AccesDossier(dossier=d25, utilisateur=dieng, est_responsable=True),
                AccesDossier(dossier=d27, utilisateur=fall, est_responsable=True),
            ]
        )
        jugement = Document(
            dossier=d27,
            titre="Jugement",
            sens=SensEchange.ENTRANT,
            chemin_fichier="D2026-0027/jugement.pdf",
            format="pdf",
        )
        email_a_trier = Communication(
            dossier_id=None,
            canal=Canal.EMAIL,
            sens=SensEchange.ENTRANT,
            date_echange=datetime(2026, 9, 20, 10, tzinfo=UTC),
            expediteur="prospect@test",
            corps="Demande de rendez-vous",
        )
        s.add_all([jugement, email_a_trier])
        s.flush()
        s.add(Extrait(document=jugement, dossier_id=d27.id, position=0, contenu="Le tribunal condamne…"))

        ids = Cabinet(dieng=dieng.id, fall=fall.id, sy=sy.id, admin=admin.id)
    yield ids
