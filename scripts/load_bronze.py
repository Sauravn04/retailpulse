"""Step 3a — Load every CSV in data/raw/ into bronze.* (PostgreSQL).

Run:  python scripts/load_bronze.py
What it does
------------
* Creates schemas + pipeline_runs (sql/01_schema.sql) if missing.
* For each *.csv in data/raw/: creates bronze.<name> with one TEXT
  column per CSV header, plus _source_file and _loaded_at.
  Bronze is deliberately all-TEXT: no cleaning, no type guessing.
  If a file's columns change, the table is rebuilt from the header —
  a rerun replaces that file's rows, never appends a second copy.
* Loads with PostgreSQL COPY (fast for 600,000 order_items), not
  row-by-row inserts.
* Verifies the loaded row count equals the CSV row count, and logs
  one row per file in pipeline_runs. Exit 1 if any file fails.
* Silver/Gold are NOT built here — see scripts/load_silver_gold.py
  (Step 3b), which needs docs/PROFILE.md column names first.

Needs: DATABASE_URL in .env, Postgres running, retailpulse DB created.
"""
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))


def _quote_ident(name: str) -> str:
    # CSV headers in this dataset are simple (letters, digits, _).
    # Reject anything else rather than building unsafe SQL.
    if not name.replace("_", "").isalnum():
        raise ValueError(f"Unsafe column/table name: {name!r}")
    return f'"{name}"'


def main() -> int:
    import psycopg2

    raw_dir = os.path.join(ROOT, "data", "raw")
    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("[FAIL] DATABASE_URL not set — copy .env.example to .env")
        return 1
    files = sorted(f for f in os.listdir(raw_dir) if f.endswith(".csv"))
    if not files:
        print("[FAIL] No CSVs in data/raw/ — download the Kaggle dataset first")
        return 1
    print(f"Loading {len(files)} files into bronze.* ...")

    conn = psycopg2.connect(url)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            with open(os.path.join(ROOT, "sql", "01_schema.sql")) as f:
                cur.execute(f.read())
            for filename in files:
                table = os.path.splitext(filename)[0]
                path = os.path.join(raw_dir, filename)
                with open(path, newline="", encoding="utf-8") as fh:
                    headers = next(csv.reader(fh))
                with open(path, encoding="utf-8") as fh:
                    n_csv = sum(1 for _ in fh) - 1  # minus header row
                cols = ", ".join(f"{_quote_ident(h)} TEXT" for h in headers)
                cur.execute(f'DROP TABLE IF EXISTS bronze.{_quote_ident(table)}')
                cur.execute(
                    f"CREATE TABLE bronze.{_quote_ident(table)} "
                    f"({cols}, _source_file TEXT, _loaded_at TIMESTAMPTZ)"
                )
                # COPY the file, then fill the audit columns.
                with open(path, encoding="utf-8") as fh:
                    cur.copy_expert(
                        f"COPY bronze.{_quote_ident(table)} "
                        f"({', '.join(_quote_ident(h) for h in headers)}) "
                        f"FROM STDIN WITH (FORMAT CSV, HEADER true)",
                        fh,
                    )
                cur.execute(
                    f"UPDATE bronze.{_quote_ident(table)} "
                    f"SET _source_file = %s, _loaded_at = now()",
                    (filename,),
                )
                cur.execute(f"SELECT count(*) FROM bronze.{_quote_ident(table)}")
                n_db = cur.fetchone()[0]
                status = "ok" if n_db == n_csv else "failed"
                print(f"  {filename}: CSV {n_csv:,} rows -> bronze.{table} {n_db:,} rows [{status}]")
                cur.execute(
                    "INSERT INTO pipeline_runs (stage, source_file, table_name, "
                    "rows_loaded, status) VALUES ('bronze', %s, %s, %s, %s)",
                    (filename, f"bronze.{table}", n_db, status),
                )
                if status == "failed":
                    raise RuntimeError(f"Row-count mismatch for {filename}: {n_csv} vs {n_db}")
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"[FAIL] Bronze load failed, rolled back: {exc}")
        return 1
    finally:
        conn.close()
    print("Bronze load OK — next: Step 3b, Silver + Gold (needs docs/PROFILE.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
