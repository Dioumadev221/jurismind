"""Ce que le CRM du cabinet apporte en plus du logiciel de gestion.

Le CRM contient la relation commerciale : opportunités (mandats en cours de négociation),
comptes rendus de rendez-vous et tâches de suivi. Ces éléments nourriront l'agent
« intelligence client » (F6), qui doit savoir ce qui s'est dit avec le client, et pas
seulement ce qui est écrit dans les dossiers.
"""

from datetime import date
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jurismind.db.base import Base, Horodatage, enum_texte
from jurismind.db.models.metier import Client


class TypeElementCrm(StrEnum):
    OPPORTUNITE = "opportunite"  # un mandat espéré ou gagné
    ACTIVITE = "activite"  # compte rendu de réunion, d'appel, de déjeuner
    TACHE = "tache"  # relance commerciale à faire


class ElementCrm(Base, Horodatage):
    """Une ligne du CRM rattachée à un client de JurisMind."""

    __tablename__ = "elements_crm"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Les identifiants du CRM sont du texte (« OPP-00012 »), pas des entiers.
    external_id: Mapped[str] = mapped_column(String(40), unique=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    type: Mapped[TypeElementCrm] = mapped_column(enum_texte(TypeElementCrm, "type_element_crm"))
    titre: Mapped[str] = mapped_column(String(300))
    contenu: Mapped[str | None] = mapped_column(Text)
    date_element: Mapped[date | None]
    montant_fcfa: Mapped[int | None] = mapped_column(BigInteger)
    statut: Mapped[str | None] = mapped_column(String(40))  # gagnee, negociation, ouverte…
    responsable: Mapped[str | None] = mapped_column(String(255))  # email de l'avocat
    donnees: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # ligne brute du CRM

    client: Mapped[Client] = relationship()

    def __repr__(self) -> str:
        return f"<ElementCrm {self.type} {self.titre!r}>"
