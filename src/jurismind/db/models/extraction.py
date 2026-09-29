"""Données structurées tirées d'un document par l'IA, en attente de relecture.

Une extraction n'est jamais une vérité : c'est une **proposition**. Un avocat la valide ou
la corrige, et c'est cette décision qui fait foi. On garde donc côte à côte ce que l'IA a
proposé, ce qui a été corrigé, et qui a tranché.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jurismind.db.base import Base, Horodatage, enum_texte
from jurismind.db.models.documents import Document
from jurismind.db.models.utilisateur import Utilisateur


class StatutExtraction(StrEnum):
    PROPOSEE = "proposee"  # l'IA a rempli, personne n'a encore relu
    VALIDEE = "validee"  # un avocat a confirmé (éventuellement après correction)
    REJETEE = "rejetee"  # un avocat a écarté l'extraction


class Extraction(Base, Horodatage):
    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    # Nom du schéma appliqué : facture, mise_en_demeure, ordonnance_injonction…
    schema: Mapped[str] = mapped_column(String(40))
    donnees: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Champs dont la valeur ne se retrouve pas telle quelle dans le document : à relire.
    champs_douteux: Mapped[list[str]] = mapped_column(JSONB, default=list)
    statut: Mapped[StatutExtraction] = mapped_column(
        enum_texte(StatutExtraction, "statut_extraction"), default=StatutExtraction.PROPOSEE
    )
    modele: Mapped[str | None] = mapped_column(String(60))  # modèle qui a produit la proposition
    valide_par_id: Mapped[int | None] = mapped_column(ForeignKey("utilisateurs.id"))
    valide_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship()
    valide_par: Mapped[Utilisateur | None] = relationship()

    @property
    def relue(self) -> bool:
        return self.statut is not StatutExtraction.PROPOSEE

    def __repr__(self) -> str:
        return f"<Extraction {self.schema} du document {self.document_id} ({self.statut})>"
