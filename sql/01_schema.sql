-- RetailPulse Step 3 — Warehouse schema (PostgreSQL 15)
-- Run:  psql -U retailpulse_user -d retailpulse -h 127.0.0.1 -f sql/01_schema.sql
-- Or:    python scripts/load_bronze.py   (creates these objects first)
-- NOTE: no table is created in the public schema. Postgres 15 gives
-- no CREATE on public by default, so pipeline_runs lives in ops.*
--
-- Bronze: raw, exactly as downloaded. Silver/Gold are created by
-- scripts/load_silver_gold.py in Step 3b, after docs/PROFILE.md
-- confirms the exact column names. Do NOT hand-write Silver tables
-- here until that file has been read.
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS quarantine;
CREATE SCHEMA IF NOT EXISTS ops;  -- run log: never use public in Postgres 15

-- One row per pipeline run, per file. This is how you prove a rerun
-- is safe: a second run of the same file must not double the rows.
CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
    run_id          SERIAL PRIMARY KEY,
    run_started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    stage           TEXT NOT NULL,          -- bronze | silver | gold
    source_file     TEXT NOT NULL,
    table_name      TEXT NOT NULL,
    rows_loaded     BIGINT NOT NULL DEFAULT 0,
    rows_quarantined BIGINT NOT NULL DEFAULT 0,
    status          TEXT NOT NULL,          -- ok | failed
    note            TEXT
);

-- Generic quarantine: one row per bad source row, with the reason.
-- Silver/Gold loaders insert here; they never silently drop a row.
CREATE TABLE IF NOT EXISTS quarantine.bad_rows (
    quarantined_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    stage           TEXT NOT NULL,
    source_file     TEXT NOT NULL,
    source_pk       TEXT,
    reason          TEXT NOT NULL,
    raw_row         TEXT
);
