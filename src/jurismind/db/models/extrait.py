"""Les extraits : les morceaux de documents et d'échanges sur lesquels travaille la recherche (RAG)."""

from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jurismind.db.base import Base
from jurismind.db.models.documents import Communication, Document

# Taille des vecteurs produits par le modèle d'embeddings (bge-m3 : 1024 nombres).
DIMENSION_VECTEURS = 1024


class Extrait(Base):
    __tablename__ = "extraits"
    __table_args__ = (
        # Un extrait vient soit d'un document, soit d'une communication : jamais des deux, jamais d'aucun.
        CheckConstraint("(document_id IS NULL) <> (communication_id IS NULL)", name="une_seule_source"),
        # Index pour la recherche par le sens (vecteurs).
        Index(
            "ix_extraits_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Index pour la recherche par mots-clés.
        Index("ix_extraits_recherche_texte", "recherche_texte", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Copié depuis le document ou l'échange, pour filtrer les droits directement ici.
    dossier_id: Mapped[int | None] = mapped_column(ForeignKey("dossiers.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    communication_id: Mapped[int | None] = mapped_column(
        ForeignKey("communications.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]  # rang de l'extrait dans sa source : 0, 1, 2…
    page: Mapped[int | None]  # page du document, pour les citations
    contenu: Mapped[str] = mapped_column(Text)
    # Vide tant que le vecteur n'a pas été calculé.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(DIMENSION_VECTEURS))
    # Calculé automatiquement par PostgreSQL à partir du contenu.
    recherche_texte: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('french', contenu)", persisted=True)
    )
    # Informations libres : titre de section, type de document…
    metadonnees: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    document: Mapped[Document | None] = relationship()
    communication: Mapped[Communication | None] = relationship()

    def __repr__(self) -> str:
        return f"<Extrait {self.id} (position {self.position})>"
