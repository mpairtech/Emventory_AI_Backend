-- Run this in your PostgreSQL database (same DB as in .env) before using search/RAG.
-- Matches MySQL emventory_admin_db: org_id + product_id per org.
-- Example: psql -U your_user -d your_db -f scripts/init_db.sql

CREATE EXTENSION IF NOT EXISTS vector;

-- If you had the old table (product_id BIGINT PK), drop it first: DROP TABLE IF EXISTS product_vectors;
CREATE TABLE IF NOT EXISTS product_vectors (
    org_id VARCHAR(255) NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    embedding vector(768) NOT NULL,
    -- Core searchable fields
    name TEXT NOT NULL,
    category TEXT,
    brand TEXT,
    -- Rich text for semantic quality
    description TEXT,
    specifications TEXT,
    -- Commerce fields
    price DOUBLE PRECISION,
    rating DOUBLE PRECISION,
    review_count DOUBLE PRECISION,
    status VARCHAR(50),
    PRIMARY KEY (org_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_product_vectors_org_id ON product_vectors (org_id);
CREATE INDEX IF NOT EXISTS idx_product_vectors_status ON product_vectors (status) WHERE status IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_product_vectors_brand ON product_vectors (brand) WHERE brand IS NOT NULL;

-- Optional: index for faster similarity search (pgvector)
-- CREATE INDEX IF NOT EXISTS product_vectors_embedding_idx ON product_vectors
--   USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
