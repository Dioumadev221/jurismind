"""Vérifie que les deux bases répondent et que pgvector est installé.

Usage : uv run python -m jurismind.db.healthcheck
"""

import sys

from sqlalchemy import text

from jurismind.db.session import get_engine, get_legacy_engine


def main() -> int:
    with get_engine().connect() as conn:
        version = conn.execute(text("SHOW server_version")).scalar_one()
        pgvector = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
    print(f"jurismind : PostgreSQL {version}, pgvector {pgvector or 'ABSENT'}")

    with get_legacy_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    print("legacy    : OK")

    return 0 if pgvector else 1


if __name__ == "__main__":
    sys.exit(main())
