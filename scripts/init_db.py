"""
Manual DB initialization helper.

This is optional because `app/main.py` already creates the pgvector extension
and tables on startup. Use this script when you want to initialize the DB
without running the API server.
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Ensure project root is on sys.path when running as a script
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from app.db.session import engine
from app.db.models.vector import Base


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    print("OK: pgvector extension ensured, tables created.")


if __name__ == "__main__":
    main()
