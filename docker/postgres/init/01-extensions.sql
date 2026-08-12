-- GeoVision — PostgreSQL extensions
--
-- Runs once, on first container start (empty data volume only). Extensions are
-- created here rather than in a migration because CREATE EXTENSION needs
-- superuser rights that the application role does not have in production.
-- Alembic migrations then assume these are available.

-- gen_random_uuid() for UUID v4 primary keys (Domain-Model.md).
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- citext: case-insensitive username and email columns, so "Jan@x.com" and
-- "jan@x.com" cannot both register.
CREATE EXTENSION IF NOT EXISTS "citext";

-- pg_trgm: trigram indexes backing the search endpoint (owner name, project
-- name, location) with fuzzy matching.
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- btree_gin: composite indexes mixing scalar columns with trigram/GIN columns.
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- Create the dedicated test database so integration tests never touch dev data.
SELECT 'CREATE DATABASE geovision_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'geovision_test')\gexec
