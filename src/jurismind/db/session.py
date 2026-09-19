"""Connexions SQLAlchemy vers la base JurisMind et la base legacy simulée."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from jurismind.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_legacy_engine() -> Engine:
    return create_engine(get_settings().legacy_database_url, pool_pre_ping=True)
