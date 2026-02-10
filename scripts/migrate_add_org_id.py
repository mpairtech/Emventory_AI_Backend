"""
Migrate product_vectors table: add org_id, change product_id to VARCHAR, new composite PK.
Run once if you have the OLD table (product_id BIGINT PK) and get "column org_id does not exist".
  python scripts/migrate_add_org_id.py
"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from sqlalchemy import text
from app.db.session import engine

MIGRATIONS = [
    "ALTER TABLE product_vectors ADD COLUMN IF NOT EXISTS org_id VARCHAR(255)",
    "UPDATE product_vectors SET org_id = 'default' WHERE org_id IS NULL",
    "ALTER TABLE product_vectors ALTER COLUMN org_id SET NOT NULL",
    "ALTER TABLE product_vectors ALTER COLUMN product_id TYPE VARCHAR(50) USING product_id::text",
    "ALTER TABLE product_vectors DROP CONSTRAINT IF EXISTS product_vectors_pkey",
    "ALTER TABLE product_vectors ADD PRIMARY KEY (org_id, product_id)",
    "CREATE INDEX IF NOT EXISTS idx_product_vectors_org_id ON product_vectors (org_id)",
]


def main():
    with engine.connect() as conn:
        for sql in MIGRATIONS:
            conn.execute(text(sql))
        conn.commit()
    print("Done: product_vectors migrated (org_id + product_id).")


if __name__ == "__main__":
    main()
