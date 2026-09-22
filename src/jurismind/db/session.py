"""Connexions à la base JurisMind et à la base legacy simulée."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from jurismind.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Connexion « propriétaire » : migrations et synchronisation. Ignore l'isolation."""
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_app_engine() -> Engine:
    """Connexion de l'application : soumise aux règles d'isolation."""
    return create_engine(get_settings().app_database_url, pool_pre_ping=True)


@lru_cache
def get_legacy_engine() -> Engine:
    return create_engine(get_settings().legacy_database_url, pool_pre_ping=True)


@contextmanager
def session_utilisateur(utilisateur_id: int) -> Iterator[Session]:
    """Ouvre une session au nom d'un utilisateur : PostgreSQL ne lui montre que ses dossiers."""
    with Session(get_app_engine()) as session, session.begin():
        session.execute(
            text("SELECT set_config('app.utilisateur_id', :id, true)"),
            {"id": str(utilisateur_id)},
        )
        yield session
