"""Step 8 (revised) — Copy Silver + Gold from local Postgres to Cloud SQL.

Run:  CLOUD_URL=postgresql://retailpulse_user:PASSWORD@CLOUD-SQL-IP:5432/retailpulse \
        python scripts/migrate_to_cloud.py
      (Windows PowerShell: $env:CLOUD_URL="postgresql://..."; python scripts/migrate_to_cloud.py)

What it does
------------
* pg_dump of the silver, gold, ops and quarantine schemas
  from your LOCAL database (DATABASE_URL in .env), then
  psql restore into Cloud SQL (CLOUD_URL env var).
  Plain-format dump, not custom: pg_dump from Postgres
  17+ writes "SET transaction_timeout = 0;" into a custom
  dump, which Cloud SQL on Postgres 15 rejects with
  "unrecognized configuration parameter". The plain dump
  is filtered to drop that line before restoring, so a
  newer local pg_dump works against an older Cloud SQL.
  Bronze is NOT copied — Gold is already built from it.
* Verifies on Cloud SQL: gold.daily_sales = 1,462 rows,
  SUM(revenue) = 3,827,746,136, forecast total = 79,543,922.
  Exits 1 if any check fails — do not point Power BI at
  Cloud SQL until this script passes.
Needs: pg_dump / psql on PATH (they come with
  PostgreSQL), local Postgres running, Cloud SQL instance
  created with the retailpulse database (see docs/CLOUD_SQL.md).
  CLOUD_URL is never written to a file or committed.
"""
import os
import socket
import subprocess
import sys
import tempfile
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

SCHEMAS = ["silver", "gold", "ops", "quarantine"]
EXPECTED = {"daily_sales_rows": 1462,
            "revenue": 3_827_746_136,
            "forecast_total": 79_543_922}


def _run(cmd, **kw):
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def main() -> int:
    local_url = os.getenv("DATABASE_URL", "")
    cloud_url = os.getenv("CLOUD_URL", "")
    if not local_url:
        print("[FAIL] DATABASE_URL not set — copy .env.example to .env")
        return 1
    if "CLOUD-SQL-IP" in cloud_url or "CHOOSE" in cloud_url:
        print("[FAIL] CLOUD_URL still contains the placeholder "
              "CLOUD-SQL-IP — replace it with the real Cloud SQL "
              "public IP from docs/CLOUD_SQL.md step 3. "
              "Create the instance first if you have not yet.")
        return 1

    # Preflight: can we even reach Cloud SQL on port 5432?
    # Fails fast with a clear message instead of dumping
    # locally and then timing out in pg_restore.
    host = urllib.parse.urlparse(cloud_url).hostname or ""
    port = urllib.parse.urlparse(cloud_url).port or 5432
    print(f"Checking we can reach Cloud SQL at {host}:{port} ...")
    try:
        with socket.create_connection((host, port), timeout=10):
            pass
    except OSError as exc:
        print(f"[FAIL] Cannot reach {host}:{port} ({exc}).")
        print("  1. That IP must be the Cloud SQL public IP from:")
        print("       gcloud sql instances describe retailpulse-db "
              "--format=\"value(ipAddresses[0].ipAddress)\"")
        print("     It is NOT your own home IP — your home IP only")
        print("     goes in --authorized-networks, never as the server.")
        print("  2. Your home IP must be in the authorized networks:")
        print("       gcloud sql instances patch retailpulse-db "
              "--authorized-networks=YOUR-HOME-IP/32")
        print("  3. The instance must be RUNNABLE:")
        print("       gcloud sql instances describe retailpulse-db "
              "--format=\"value(state)\"")
        return 1
    print("  Reachable.")

    with tempfile.TemporaryDirectory() as tmp:
        dump = os.path.join(tmp, "retailpulse_gold.sql")
        print("Dumping silver/gold/ops/quarantine from local Postgres ...")
        cmd = ["pg_dump", local_url, "--format=plain", "--no-owner",
               "--clean", "--if-exists", "--file", dump]
        for s in SCHEMAS:
            cmd += ["--schema", s]
        _run(cmd)
        # Strip PG17+ settings the older Cloud SQL server
        # does not know (see docstring). Only that one SET
        # line is removed; nothing else is edited.
        with open(dump, encoding="utf-8") as f:
            lines = f.readlines()
        kept = [ln for ln in lines
                if not ln.strip().startswith("SET transaction_timeout")]
        if len(kept) != len(lines):
            print(f"  Removed {len(lines) - len(kept)} "
                  "transaction_timeout line(s) (PG17+ only).")
            with open(dump, "w", encoding="utf-8") as f:
                f.writelines(kept)
        print("Restoring into Cloud SQL ...")
        _run(["psql", cloud_url, "-v", "ON_ERROR_STOP=1",
              "-q", "-f", dump])

    print("\nVerifying on Cloud SQL ...")
    import psycopg2

    conn = psycopg2.connect(cloud_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM gold.daily_sales")
            n = cur.fetchone()[0]
            print(f"  gold.daily_sales rows: {n:,} "
                  f"(expected {EXPECTED['daily_sales_rows']:,})")
            if n != EXPECTED["daily_sales_rows"]:
                return 1
            cur.execute("SELECT COALESCE(SUM(revenue), 0) "
                        "FROM gold.daily_sales")
            rev = int(cur.fetchone()[0])
            print(f"  gold.daily_sales revenue: {rev:,} "
                  f"(expected {EXPECTED['revenue']:,})")
            if rev != EXPECTED["revenue"]:
                return 1
            cur.execute("SELECT ROUND(COALESCE(SUM(forecast), 0)) "
                        "FROM gold.forecast_daily")
            # ROUND, not int(): forecast is a float (rolling mean),
            # so SUM is e.g. 79,543,921.6 — int() would truncate
            # it to 79,543,921, while the Step 6 total
            # 79,543,922 was rounded. A 1-unit difference here
            # is rounding, not missing data.
            fc = int(cur.fetchone()[0])
            print(f"  gold.forecast_daily total: {fc:,} "
                  f"(expected {EXPECTED['forecast_total']:,})")
            if fc != EXPECTED["forecast_total"]:
                return 1
    finally:
        conn.close()
    print("\nMigration OK — Cloud SQL matches local Gold. "
          "Now do docs/CLOUD_SQL.md step 7 (Power BI).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
