#!/bin/sh
# GeoVision — mirror the extensions into the test database.
#
# 01-extensions.sql creates geovision_test, but extensions are per-database, so
# the test database needs its own. Without this, integration tests fail on
# gen_random_uuid() in a way that looks like a migration bug rather than a
# missing extension.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname geovision_test <<-'EOSQL'
    CREATE EXTENSION IF NOT EXISTS "pgcrypto";
    CREATE EXTENSION IF NOT EXISTS "citext";
    CREATE EXTENSION IF NOT EXISTS "pg_trgm";
    CREATE EXTENSION IF NOT EXISTS "btree_gin";
EOSQL

echo "test database extensions ready"
