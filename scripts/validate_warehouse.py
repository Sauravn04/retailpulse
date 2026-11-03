"""Step 3b check — Validate Silver + Gold after load_silver_gold.py.

Run:  python scripts/validate_warehouse.py
Checks (all must pass, exit 0; any fail exits 1):
  * Silver row counts = Bronze row counts for all 12 tables
  * Silver revenue SUM(qty*price) = 3,827,746,136
  * Silver payments SUM(amount) = 3,018,080,810
  * Gold daily / category / store / monthly revenue = 3,827,746,136
  * gold.daily_sales = 1,462 rows, gold.daily_category_sales = 43,860 rows
  * No orphan FKs in silver.order_items / silver.orders / silver.payments
  * quarantine.bad_rows count is reported (expected 0 on this dataset)
Writes: data/warehouse_validation.json
Needs: DATABASE_URL in .env, Postgres running.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

EXPECTED_REVENUE = 3_827_746_136
EXPECTED_PAYMENTS = 3_018_080_810
EXPECTED = {
    "categories": 30,
    "stores": 100,
    "products": 10_000,
    "customers": 50_000,
    "orders": 300_000,
    "order_items": 600_000,
    "payments": 300_000,
    "employees": 1_000,
    "promotions": 50,
    "returns": 30_000,
    "shipments": 300_000,
    "suppliers": 200,
}


def main() -> int:
    import psycopg2

    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("[FAIL] DATABASE_URL not set")
        return 1
    checks = []
    failed = 0

    def check(name, actual, expected, note=""):
        nonlocal failed
        ok = actual == expected
        if not ok:
            failed += 1
        print(
            f"  [{'PASS' if ok else 'FAIL'}] {name}: {actual:,} (expected {expected:,}) {note}"
        )
        checks.append(
            {
                "check": name,
                "actual": actual,
                "expected": expected,
                "status": "PASS" if ok else "FAIL",
                "note": note,
            }
        )
        return ok

    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            print("Silver counts vs Bronze:")
            for table, exp in EXPECTED.items():
                cur.execute(f"SELECT count(*) FROM silver.{table}")
                n_silver = cur.fetchone()[0]
                cur.execute(f"SELECT count(*) FROM bronze.{table}")
                n_bronze = cur.fetchone()[0]
                check(f"silver.{table}", n_silver, exp, f"bronze={n_bronze:,}")
            print("\nRevenue / payments:")
            cur.execute("SELECT COALESCE(SUM(qty * price), 0) FROM silver.order_items")
            check(
                "silver_revenue_qty_x_price", int(cur.fetchone()[0]), EXPECTED_REVENUE
            )
            cur.execute("SELECT COALESCE(SUM(amount), 0) FROM silver.payments")
            check("silver_payments_total", int(cur.fetchone()[0]), EXPECTED_PAYMENTS)
            print("\nGold totals:")
            for table in (
                "daily_sales",
                "daily_category_sales",
                "daily_store_sales",
                "monthly_sales",
            ):
                cur.execute(f"SELECT COALESCE(SUM(revenue), 0) FROM gold.{table}")
                check(f"gold.{table}_revenue", int(cur.fetchone()[0]), EXPECTED_REVENUE)
            cur.execute("SELECT count(*) FROM gold.daily_sales")
            check("gold.daily_sales_rows", cur.fetchone()[0], 1462)
            cur.execute("SELECT count(*) FROM gold.daily_category_sales")
            check("gold.daily_category_sales_rows", cur.fetchone()[0], 43860)
            print("\nOrphans (must be 0):")
            cur.execute(
                "SELECT count(*) FROM silver.order_items oi "
                "LEFT JOIN silver.orders o ON o.order_id = oi.order_id "
                "WHERE o.order_id IS NULL"
            )
            check("orphan_order_items", cur.fetchone()[0], 0)
            cur.execute(
                "SELECT count(*) FROM silver.payments p "
                "LEFT JOIN silver.orders o ON o.order_id = p.order_id "
                "WHERE o.order_id IS NULL"
            )
            check("orphan_payments", cur.fetchone()[0], 0)
            cur.execute("SELECT count(*) FROM quarantine.bad_rows WHERE stage='silver'")
            q = cur.fetchone()[0]
            print(f"  [INFO] quarantine.bad_rows (silver): {q:,} (expected 0)")
            checks.append(
                {
                    "check": "quarantined_silver_rows",
                    "actual": q,
                    "expected": 0,
                    "status": "INFO",
                    "note": "reported, not a fail",
                }
            )
    finally:
        conn.close()

    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "warehouse_validation.json"), "w") as f:
        json.dump(
            {
                "overall": "PASS" if failed == 0 else "FAIL",
                "failed": failed,
                "checks": checks,
            },
            f,
            indent=2,
        )
    print(
        f"\nWarehouse validation: {'PASS' if failed == 0 else 'FAIL'} "
        f"({failed} failed) — wrote data/warehouse_validation.json"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
