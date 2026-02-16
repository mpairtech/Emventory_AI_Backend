-- Migration: Remove tags column from product_vectors
-- Run: psql -U your_user -d your_db -f scripts/migrate_remove_tags.sql

-- Drop tags column (if it exists)
ALTER TABLE product_vectors DROP COLUMN IF EXISTS tags;

COMMENT ON TABLE product_vectors IS 'Vector store for AI search - tags column removed';
