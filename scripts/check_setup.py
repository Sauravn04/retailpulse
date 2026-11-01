"""Step 1 setup check for RetailPulse.

Run:  python scripts/check_setup.py
Checks Python version, Git, required packages, and (optionally)
PostgreSQL reachability from DATABASE_URL in .env.
Postgres DOWN is a warning in Step 1, not a failure — Step 3 needs it.
Exit 0 if core checks pass, 1 if Python/packages/Git fail.
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REQUIRED = ["pandas", "numpy", "sqlalchemy", "psycopg2", "sklearn", "fastapi", "dotenv"]


def main():
    print("RetailPulse — Step 1 setup check")
    print(f"Python: {sys.version.split()[0]} (need 3.11+)")
    ok = True
    if sys.version_info < (3, 11):
        print("[FAIL] Python 3.11+ required")
        ok = False
    else:
        print("[PASS] Python version")

    git = shutil.which("git")
    print(f"[{'PASS' if git else 'FAIL'}] Git: {git or 'not found on PATH'}")
    if not git:
        ok = False

    for pkg in REQUIRED:
        try:
            __import__(pkg)
            print(f"[PASS] package: {pkg}")
        except ImportError:
            print(f"[FAIL] package missing: {pkg} — run: pip install -r requirements.txt")
            ok = False

    # Postgres: try only if a DATABASE_URL is configured.
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except Exception:
        pass
    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("[WARN] DATABASE_URL not set — copy .env.example to .env (Step 3 needs Postgres)")
    else:
        try:
            from sqlalchemy import create_engine, text
            eng = create_engine(url, connect_args={"connect_timeout": 3})
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("[PASS] PostgreSQL reachable")
        except Exception as exc:
            print(f"[WARN] PostgreSQL not reachable: {exc}")
            print("       Start Postgres and check .env — needed from Step 3.")

    print("\nSETUP OK" if ok else "\nSETUP FAILED — fix the [FAIL] lines above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
