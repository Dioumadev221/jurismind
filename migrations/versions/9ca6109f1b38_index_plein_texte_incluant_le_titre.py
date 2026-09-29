"""index plein texte incluant le titre

Revision ID: 9ca6109f1b38
Revises: c2dbd772e8f2
Create Date: 2026-09-29 19:19:11.885321

"""

from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9ca6109f1b38"
down_revision: Union[str, Sequence[str], None] = "c2dbd772e8f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _remplacer_colonne(expression: str) -> None:
    """La colonne est calculée par PostgreSQL : on la recrée, et l'index avec elle."""
    op.execute("DROP INDEX IF EXISTS ix_extraits_recherche_texte")
    op.execute("ALTER TABLE extraits DROP COLUMN recherche_texte")
    op.execute(
        "ALTER TABLE extraits ADD COLUMN recherche_texte tsvector "
        f"GENERATED ALWAYS AS ({expression}) STORED NOT NULL"
    )
    op.execute("CREATE INDEX ix_extraits_recherche_texte ON extraits USING gin (recherche_texte)")


def upgrade() -> None:
    """Indexe aussi le titre du document : sur un scan, l'OCR détruit parfois le numéro de
    la pièce, alors que le titre venu du logiciel du cabinet le conserve."""
    _remplacer_colonne("to_tsvector('french', coalesce(metadonnees->>'titre', '') || ' ' || contenu)")


def downgrade() -> None:
    _remplacer_colonne("to_tsvector('french', contenu)")
