"""Tables techniques : le journal d'audit et la file de tâches de fond."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from jurismind.db.base import Base, Horodatage, enum_texte


class EntreeAudit(Base):
    """Une ligne par action sensible : qui a fait quoi, sur quoi, et quand. On n'y écrit qu'en ajout."""

    __tablename__ = "journal_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Vide pour une action du système lui-même (synchronisation, tâche de fond).
    utilisateur_id: Mapped[int | None] = mapped_column(ForeignKey("utilisateurs.id"), index=True)
    action: Mapped[str] = mapped_column(String(60))  # ex. « question_ia », « validation_envoi »
    dossier_id: Mapped[int | None] = mapped_column(index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<EntreeAudit {self.action} par {self.utilisateur_id}>"


class StatutTache(StrEnum):
    EN_ATTENTE = "en_attente"
    EN_COURS = "en_cours"
    TERMINEE = "terminee"
    ECHEC = "echec"


class Tache(Base, Horodatage):
    """Un travail long à faire en arrière-plan : lire un document, calculer des vecteurs…"""

    __tablename__ = "taches"
    __table_args__ = (Index("ix_taches_a_faire", "statut", "executer_apres"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(40))  # ex. « ingerer_document »
    parametres: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # ex. {"document_id": 184}
    statut: Mapped[StatutTache] = mapped_column(
        enum_texte(StatutTache, "statut_tache"), default=StatutTache.EN_ATTENTE
    )
    tentatives: Mapped[int] = mapped_column(default=0)
    executer_apres: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    erreur: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<Tache {self.id} {self.type} ({self.statut})>"
