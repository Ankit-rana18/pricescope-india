-- Runs once when the Postgres volume is first created.
-- Migrations also create these (idempotently) so managed databases work without this file.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;
