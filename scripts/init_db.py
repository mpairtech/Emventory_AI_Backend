"""
Manual DB initialization helper.

This is optional because `app/main.py` already creates the pgvector extension
and tables on startup. Use this script when you want to initialize the DB
without running the API server.
"""

from sqlalchemy import text

from app.db.session import engine
from app.db.models.vector import Base


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    print("OK: pgvector extension ensured, tables created.")


if __name__ == "__main__":
    main()

"""
Create pgvector extension and product_vectors table. Run once before using search/RAG.
  python scripts/init_db.py
Uses .env for DB connection (same as the app).
"""
import sys
from pathlib import Path

# app import করার জন্য project root in path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from sqlalchemy import text
from app.db.session import engine
from app.db.models.vector import Base

def main():
    # Create pgvector extension
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    print("Done: pgvector extension + product_vectors table created.")

if __name__ == "__main__":
    main()
