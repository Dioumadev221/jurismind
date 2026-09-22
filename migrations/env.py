"""Configuration d'Alembic : à quelle base se connecter, et quelles tables comparer."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import jurismind.db.models  # noqa: F401  (inscrit toutes les tables dans Base.metadata)
from jurismind.core.config import get_settings
from jurismind.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Le « catalogue » de nos tables : Alembic le compare à la base pour savoir quoi créer.
target_metadata = Base.metadata
# L'adresse de la base vient de notre configuration (.env), pas d'alembic.ini.
URL = get_settings().database_url


def run_migrations_offline() -> None:
    """Mode « hors ligne » : écrit le SQL à l'écran au lieu de l'exécuter."""
    context.configure(url=URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Mode normal : se connecte à la base et applique les migrations."""
    engine = create_engine(URL, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()