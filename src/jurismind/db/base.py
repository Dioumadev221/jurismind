"""
Classe de base commune à tous les modeles ==> table de JurisMind.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

CONVENTIONS = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENTIONS)


class Horodatage:
    """
    A ajouter a la table pour savoir quand chanque ligne a ete crée et modifiée.
    """

    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def enum_texte(enum: type[StrEnum], nom: str) -> Enum:
    """Stocke une énumération comme du texte, avec une contrainte qui refuse toute autre valeur."""
    return Enum(
        enum,
        name=nom,
        native_enum=False,
        create_constraint=True,
        length=30,
        values_callable=lambda valeurs: [v.value for v in valeurs],
    )
