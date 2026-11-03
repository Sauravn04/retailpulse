"""Step 4 — Run SQL analytics + check the answers.

Run:  python scripts/run_analytics.py
What it does
------------
* Runs sql/02_analytics.sql (views + gold.rfm_customers, idempotent).
* Checks the analytics are internally consistent, then prints the
  headline business answers: top categories/stores, latest daily
  trend (7d rolling, week-on-week), latest monthly trend, and the
  RFM segment counts.
* Writes data/analytics_report.json with those numbers.
Needs: DATABASE_URL in .env, Postgres running, Step 3b done
  (Gold tables must exist — run scripts/load_silver_gold.py first).
Exit 0 = all checks PASS, 1 = any check FAIL.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

EXPECTED_REVENUE = 3_827_746_136


def main() -> int:
    import psycopg2

    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("[FAIL] DATABASE_URL not set")
        return 1
    checks = []
    failed = 0
    report = {}

    def check(name, actual, expected, note=""):
        nonlocal failed
        ok = actual == expected
        if not ok:
            failed += 1
        print(
            f"  [{'PASS' if ok else 'FAIL'}] {name}: {actual} "
            f"(expected {expected}) {note}"
        )
        checks.append(
            {
                "check": name,
                "actual": str(actual),
                "expected": str(expected),
                "status": "PASS" if ok else "FAIL",
                "note": note,
            }
        )
        return ok

    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            with open(os.path.join(ROOT, "sql", "02_analytics.sql")) as f:
                cur.execute(f.read())
        conn.commit()
        print("Analytics SQL applied (sql/02_analytics.sql).")

        with conn.cursor() as cur:
            print("\nChecks:")
            cur.execute("SELECT count(*) FROM gold.v_daily_trend")
            check("v_daily_trend_rows", cur.fetchone()[0], 1462)
            cur.execute("SELECT count(*) FROM gold.v_top_categories")
            check("v_top_categories_rows", cur.fetchone()[0], 30)
            cur.execute("SELECT count(*) FROM gold.v_top_stores")
            check("v_top_stores_rows", cur.fetchone()[0], 100)
            cur.execute("SELECT count(*) FROM gold.v_monthly_trend")
            check("v_monthly_trend_rows", cur.fetchone()[0], 49)
            cur.execute("SELECT COALESCE(SUM(revenue), 0) FROM gold.v_top_categories")
            check("top_categories_revenue", int(cur.fetchone()[0]), EXPECTED_REVENUE)
            cur.execute("SELECT COALESCE(SUM(revenue), 0) FROM gold.v_top_stores")
            check("top_stores_revenue", int(cur.fetchone()[0]), EXPECTED_REVENUE)
            cur.execute(
                "SELECT cumulative_revenue FROM gold.v_daily_trend "
                "ORDER BY order_date DESC LIMIT 1"
            )
            check(
                "daily_trend_cumulative_revenue",
                int(cur.fetchone()[0]),
                EXPECTED_REVENUE,
            )
            cur.execute("SELECT COALESCE(SUM(monetary), 0) FROM gold.rfm_customers")
            check("rfm_monetary_total", int(cur.fetchone()[0]), EXPECTED_REVENUE)
            cur.execute(
                "SELECT count(*) FROM gold.rfm_customers "
                "WHERE r_score NOT BETWEEN 1 AND 5 "
                "OR f_score NOT BETWEEN 1 AND 5 "
                "OR m_score NOT BETWEEN 1 AND 5"
            )
            check("rfm_scores_out_of_range", cur.fetchone()[0], 0)
            cur.execute("SELECT count(*) FROM gold.rfm_customers")
            n_rfm = cur.fetchone()[0]
            print(f"  [INFO] rfm_customers rows: {n_rfm:,}")
            report["rfm_customers"] = n_rfm
            cur.execute(
                "SELECT count(*) FROM silver.customers c "
                "WHERE NOT EXISTS (SELECT 1 FROM silver.orders o "
                "WHERE o.customer_id = c.customer_id)"
            )
            n_no_orders = cur.fetchone()[0]
            print(
                f"  [INFO] customers with no orders (not in RFM): " f"{n_no_orders:,}"
            )
            report["customers_without_orders"] = n_no_orders

            print("\nTop 5 categories by revenue:")
            cur.execute(
                "SELECT category_id, revenue, revenue_share_pct, "
                "revenue_rank FROM gold.v_top_categories "
                "ORDER BY revenue_rank LIMIT 5"
            )
            top_cats = []
            for cid, rev, share, rank in cur.fetchall():
                print(
                    f"  #{rank} category {cid}: {int(rev):,} " f"({share}% of revenue)"
                )
                top_cats.append(
                    {
                        "category_id": cid,
                        "revenue": int(rev),
                        "share_pct": float(share),
                        "rank": rank,
                    }
                )
            report["top_categories"] = top_cats

            print("\nTop 5 stores by revenue:")
            cur.execute(
                "SELECT store_id, revenue, revenue_share_pct, "
                "revenue_rank FROM gold.v_top_stores "
                "ORDER BY revenue_rank LIMIT 5"
            )
            top_stores = []
            for sid, rev, share, rank in cur.fetchall():
                print(f"  #{rank} store {sid}: {int(rev):,} " f"({share}% of revenue)")
                top_stores.append(
                    {
                        "store_id": sid,
                        "revenue": int(rev),
                        "share_pct": float(share),
                        "rank": rank,
                    }
                )
            report["top_stores"] = top_stores

            print("\nLatest day (last row of v_daily_trend):")
            cur.execute(
                "SELECT order_date, revenue, rolling_7d_revenue, "
                "rolling_30d_revenue, wow_pct, cumulative_revenue "
                "FROM gold.v_daily_trend ORDER BY order_date DESC LIMIT 1"
            )
            d, rev, r7, r30, wow, cum = cur.fetchone()
            print(
                f"  {d}: revenue {int(rev):,}, 7d avg {float(r7):,.0f}, "
                f"30d avg {float(r30):,.0f}, WoW {wow}%, "
                f"cumulative {int(cum):,}"
            )
            report["latest_day"] = {
                "date": str(d),
                "revenue": int(rev),
                "rolling_7d": float(r7),
                "rolling_30d": float(r30),
                "wow_pct": float(wow) if wow is not None else None,
                "cumulative_revenue": int(cum),
            }

            print("\nLatest month (last row of v_monthly_trend):")
            cur.execute(
                "SELECT month, revenue, mom_pct FROM gold.v_monthly_trend "
                "ORDER BY month DESC LIMIT 1"
            )
            m, rev, mom = cur.fetchone()
            print(f"  {m}: revenue {int(rev):,}, MoM {mom}%")
            report["latest_month"] = {
                "month": str(m),
                "revenue": int(rev),
                "mom_pct": float(mom) if mom is not None else None,
            }

            print("\nRFM segments:")
            cur.execute(
                "SELECT segment, count(*) FROM gold.rfm_customers "
                "GROUP BY segment ORDER BY count(*) DESC"
            )
            segments = {}
            for seg, n in cur.fetchall():
                print(f"  {seg}: {n:,}")
                segments[seg] = n
            report["rfm_segments"] = segments
    finally:
        conn.close()

    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "analytics_report.json"), "w") as f:
        json.dump(
            {
                "overall": "PASS" if failed == 0 else "FAIL",
                "failed": failed,
                "checks": checks,
                "report": report,
            },
            f,
            indent=2,
        )
    print(
        f"\nAnalytics: {'PASS' if failed == 0 else 'FAIL'} "
        f"({failed} failed) — wrote data/analytics_report.json"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
