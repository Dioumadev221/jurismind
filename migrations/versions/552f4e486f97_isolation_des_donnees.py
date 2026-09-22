"""isolation des donnees

Revision ID: 552f4e486f97
Revises: d67875560077
Create Date: 2026-09-22 14:57:33.242984

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa

from jurismind.core.config import get_settings


# revision identifiers, used by Alembic.
revision: str = '552f4e486f97'
down_revision: Union[str, Sequence[str], None] = 'd67875560077'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables dont chaque ligne appartient à un dossier (colonne dossier_id).
TABLES_DU_DOSSIER = ["acces_dossiers", "parties", "documents"]
# Tables qui contiennent aussi des éléments pas encore rattachés à un dossier (emails à trier).
TABLES_A_TRIER = ["communications", "extraits"]
TOUTES = ["dossiers", "clients", "contacts", "pieces_jointes", *TABLES_DU_DOSSIER, *TABLES_A_TRIER]


def upgrade() -> None:
    """Active l'isolation : chaque utilisateur ne voit que les dossiers auxquels il a accès."""
    reglages = get_settings()
    role = reglages.postgres_app_user
    mot_de_passe = reglages.postgres_app_password.get_secret_value().replace("'", "''")

    # 1. L'utilisateur PostgreSQL de l'application : sans super-pouvoirs, donc soumis aux règles.
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} LOGIN PASSWORD '{mot_de_passe}';
            END IF;
        END $$;
    """)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}"
    )
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role}")

    # 2. Trois petites fonctions utilisées par les règles.
    op.execute("""
        CREATE FUNCTION utilisateur_courant() RETURNS integer
        LANGUAGE sql STABLE AS $$
            SELECT nullif(current_setting('app.utilisateur_id', true), '')::integer
        $$
    """)
    op.execute("""
        CREATE FUNCTION dossiers_autorises() RETURNS SETOF integer
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
            SELECT dossier_id FROM acces_dossiers WHERE utilisateur_id = utilisateur_courant()
        $$
    """)
    op.execute("""
        CREATE FUNCTION role_courant() RETURNS text
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
            SELECT role FROM utilisateurs WHERE id = utilisateur_courant() AND actif
        $$
    """)

    # 3. Les règles, table par table.
    for table in TOUTES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    op.execute("CREATE POLICY isolation ON dossiers USING (id IN (SELECT dossiers_autorises()))")
    for table in TABLES_DU_DOSSIER:
        op.execute(
            f"CREATE POLICY isolation ON {table} USING (dossier_id IN (SELECT dossiers_autorises()))"
        )
    for table in TABLES_A_TRIER:
        op.execute(f"""
            CREATE POLICY isolation ON {table} USING (
                dossier_id IN (SELECT dossiers_autorises())
                OR (dossier_id IS NULL AND role_courant() IN ('avocat', 'assistant'))
            )
        """)
    op.execute("CREATE POLICY isolation ON clients USING (id IN (SELECT client_id FROM dossiers))")
    op.execute("CREATE POLICY isolation ON contacts USING (client_id IN (SELECT id FROM clients))")
    op.execute("""
        CREATE POLICY isolation ON pieces_jointes
        USING (EXISTS (SELECT 1 FROM communications c WHERE c.id = communication_id))
    """)


def downgrade() -> None:
    """Retire l'isolation."""
    role = get_settings().postgres_app_user
    for table in TOUTES:
        op.execute(f"DROP POLICY IF EXISTS isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS role_courant()")
    op.execute("DROP FUNCTION IF EXISTS dossiers_autorises()")
    op.execute("DROP FUNCTION IF EXISTS utilisateur_courant()")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {role}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {role}")
    op.execute(f"DROP OWNED BY {role}")
    op.execute(f"DROP ROLE IF EXISTS {role}")