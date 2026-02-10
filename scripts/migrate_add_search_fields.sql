-- Migration: Add brand, description, tags, status, specifications columns to product_vectors
-- Run: psql -U your_user -d your_db -f scripts/migrate_add_search_fields.sql

-- Add new columns for better search indexing
ALTER TABLE product_vectors 
ADD COLUMN IF NOT EXISTS brand TEXT,
ADD COLUMN IF NOT EXISTS description TEXT,
ADD COLUMN IF NOT EXISTS status VARCHAR(50),
ADD COLUMN IF NOT EXISTS specifications TEXT,
ADD COLUMN IF NOT EXISTS rating DOUBLE PRECISION,
ADD COLUMN IF NOT EXISTS review_count DOUBLE PRECISION;

-- Optional: Add index on status for filtering active products
CREATE INDEX IF NOT EXISTS idx_product_vectors_status ON product_vectors (status) WHERE status IS NOT NULL;

-- Optional: Add index on brand for brand-based filtering
CREATE INDEX IF NOT EXISTS idx_product_vectors_brand ON product_vectors (brand) WHERE brand IS NOT NULL;

COMMENT ON COLUMN product_vectors.brand IS 'Product brand/manufacturer for better search';
COMMENT ON COLUMN product_vectors.description IS 'Product description/details';
COMMENT ON COLUMN product_vectors.status IS 'Product status (e.g., ACTIVE, INACTIVE, DRAFT)';
COMMENT ON COLUMN product_vectors.specifications IS 'Technical specifications/details';
COMMENT ON COLUMN product_vectors.rating IS 'Average rating from review table (0-5 stars)';
COMMENT ON COLUMN product_vectors.review_count IS 'Number of reviews';
