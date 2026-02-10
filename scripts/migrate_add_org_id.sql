-- Migrate product_vectors from old schema (product_id BIGINT PK) to new (org_id + product_id).
-- Run if you already have the old table: psql -U your_user -d your_db -f scripts/migrate_add_org_id.sql

-- 1. Add org_id (existing rows get 'default')
ALTER TABLE product_vectors ADD COLUMN IF NOT EXISTS org_id VARCHAR(255);
UPDATE product_vectors SET org_id = 'default' WHERE org_id IS NULL;
ALTER TABLE product_vectors ALTER COLUMN org_id SET NOT NULL;

-- 2. Change product_id from BIGINT to VARCHAR(50)
ALTER TABLE product_vectors ALTER COLUMN product_id TYPE VARCHAR(50) USING product_id::text;

-- 3. Drop old primary key
ALTER TABLE product_vectors DROP CONSTRAINT IF EXISTS product_vectors_pkey;

-- 4. Add new composite primary key
ALTER TABLE product_vectors ADD PRIMARY KEY (org_id, product_id);

-- 5. Index for org filter
CREATE INDEX IF NOT EXISTS idx_product_vectors_org_id ON product_vectors (org_id);
