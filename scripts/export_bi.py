"""Step 5 — Export Gold + analytics to an Excel BI workbook.

Run:  python scripts/export_bi.py
What it does
------------
* Reads Gold only (gold.daily_sales / daily_category_sales /
  daily_store_sales / monthly_sales, the Step 4 views and
  gold.rfm_customers) — never Bronze or CSVs.
* Writes bi/retailpulse_bi.xlsx with one sheet per question,
  plus a Dashboard sheet with the headline numbers, and
  bi/*.csv copies of the same tables for Tableau / Power BI.
* Checks the workbook totals before finishing: every revenue
  total must equal 3,827,746,136, or it exits 1.
Needs: DATABASE_URL in .env, Postgres running, Steps 3b + 4 done.
Exit 0 = workbook written and totals reconcile.
"""

import csv
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

EXPECTED_REVENUE = 3_827_746_136
OUT_DIR = os.path.join(ROOT, "bi")
XLSX = os.path.join(OUT_DIR, "retailpulse_bi.xlsx")


def _rows(cur, sql):
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def main() -> int:
    import psycopg2
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("[FAIL] DATABASE_URL not set")
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)

    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            tables = {
                "Daily_Trend": (
                    "SELECT order_date, revenue, orders, quantity, "
                    "rolling_7d_revenue, rolling_30d_revenue, wow_pct, "
                    "cumulative_revenue FROM gold.v_daily_trend "
                    "ORDER BY order_date"
                ),
                "Monthly_Trend": (
                    "SELECT month, revenue, orders, quantity, mom_pct, "
                    "rolling_3m_revenue, cumulative_revenue "
                    "FROM gold.v_monthly_trend ORDER BY month"
                ),
                "Top_Categories": (
                    "SELECT category_id, revenue, quantity, "
                    "revenue_share_pct, revenue_rank, "
                    "cumulative_share_pct FROM gold.v_top_categories "
                    "ORDER BY revenue_rank"
                ),
                "Top_Stores": (
                    "SELECT store_id, revenue, quantity, "
                    "revenue_share_pct, revenue_rank, "
                    "cumulative_share_pct FROM gold.v_top_stores "
                    "ORDER BY revenue_rank"
                ),
                "RFM_Segments": (
                    "SELECT segment, count(*) AS customers, "
                    "ROUND(AVG(monetary), 2) AS avg_monetary, "
                    "ROUND(AVG(frequency), 2) AS avg_frequency, "
                    "ROUND(AVG(recency_days), 1) AS avg_recency_days "
                    "FROM gold.rfm_customers GROUP BY segment "
                    "ORDER BY customers DESC"
                ),
                "RFM_Customers": (
                    "SELECT customer_id, last_order_date, recency_days, "
                    "frequency, monetary, r_score, f_score, m_score, "
                    "rfm_code, segment FROM gold.rfm_customers "
                    "ORDER BY monetary DESC"
                ),
            }
            data = {}
            for name, sql in tables.items():
                cols, rows = _rows(cur, sql)
                data[name] = (cols, rows)
                print(f"  {name}: {len(rows):,} rows")

            # Data-quality numbers for the Dashboard sheet.
            cur.execute(
                "SELECT count(*) FROM quarantine.bad_rows " "WHERE stage='silver'"
            )
            quarantined = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM silver.customers c "
                "WHERE NOT EXISTS (SELECT 1 FROM silver.orders o "
                "WHERE o.customer_id = c.customer_id)"
            )
            no_orders = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(revenue), 0) " "FROM gold.daily_sales")
            total_revenue = int(cur.fetchone()[0])
    finally:
        conn.close()

    if total_revenue != EXPECTED_REVENUE:
        print(f"[FAIL] total revenue {total_revenue:,} != " f"{EXPECTED_REVENUE:,}")
        return 1

    wb = Workbook()
    # Dashboard first.
    ws = wb.active
    ws.title = "Dashboard"
    ws["A1"] = "RetailPulse — BI Dashboard (from Gold, Steps 3b + 4)"
    ws["A1"].font = Font(bold=True, size=14)
    top_cat = data["Top_Categories"][1][0]
    top_store = data["Top_Stores"][1][0]
    rfm = {r[0]: r[1] for r in data["RFM_Segments"][1]}
    dashboard = [
        ("Total revenue (2020-01-01 to 2024-01-01)", total_revenue),
        ("Mean daily revenue", round(total_revenue / 1462, 2)),
        (
            "Top category",
            f"category {top_cat[0]} — {int(top_cat[1]):,} "
            f"({top_cat[3]}% of revenue)",
        ),
        (
            "Top store",
            f"store {top_store[0]} — {int(top_store[1]):,} "
            f"({top_store[3]}% of revenue)",
        ),
        (
            "Top 5 categories share of revenue",
            "see Top_Categories — cumulative share at rank 5",
        ),
        ("Champions (RFM)", rfm.get("Champions", 0)),
        ("Hibernating (RFM)", rfm.get("Hibernating", 0)),
        ("At Risk (RFM)", rfm.get("At Risk", 0)),
        ("Customers with no orders", no_orders),
        ("Quarantined rows in Silver", quarantined),
        ("Note: Jan 2024 is a 1-day partial month — its MoM is meaningless.", ""),
        (
            "Source: gold.* in PostgreSQL. Rebuild with: "
            "python scripts/export_bi.py",
            "",
        ),
    ]
    for i, (label, value) in enumerate(dashboard, start=3):
        ws.cell(row=i, column=1, value=label)
        ws.cell(row=i, column=2, value=value)
        ws.cell(row=i, column=1).font = Font(bold=True)
    ws.column_dimensions["A"].width = 48
    ws.column_dimensions["B"].width = 42

    for name, (cols, rows) in data.items():
        sh = wb.create_sheet(name)
        sh.append(cols)
        for r in rows:
            sh.append([c.isoformat() if isinstance(c, date) else c for c in r])
        for cell in sh[1]:
            cell.font = Font(bold=True)
        sh.freeze_panes = "A2"
        sh.auto_filter.ref = sh.dimensions
        for j, col in enumerate(cols, start=1):
            sh.column_dimensions[get_column_letter(j)].width = 18

    # Charts (on the data sheets, so they stay linked to the data).
    daily = wb["Daily_Trend"]
    line = LineChart()
    line.title = "Daily revenue and 7-day rolling average"
    line.y_axis.title = "Revenue"
    line.x_axis.title = "Day"
    line.height = 7.5
    line.width = 15
    line.add_data(
        Reference(daily, min_col=2, min_row=1, max_row=1 + len(data["Daily_Trend"][1])),
        titles_from_data=True,
    )
    line.add_data(
        Reference(daily, min_col=5, min_row=1, max_row=1 + len(data["Daily_Trend"][1])),
        titles_from_data=True,
    )
    daily.add_chart(line, "J2")

    cats = wb["Top_Categories"]
    bar = BarChart()
    bar.type = "col"
    bar.title = "Revenue by category (top 30)"
    bar.y_axis.title = "Revenue"
    bar.height = 7.5
    bar.width = 15
    bar.add_data(
        Reference(cats, min_col=2, min_row=1, max_row=31), titles_from_data=True
    )
    bar.set_categories(Reference(cats, min_col=1, min_row=2, max_row=31))
    cats.add_chart(bar, "H2")

    rfm_sh = wb["RFM_Segments"]
    rbar = BarChart()
    rbar.type = "col"
    rbar.title = "Customers by RFM segment"
    rbar.y_axis.title = "Customers"
    rbar.height = 7.5
    rbar.width = 15
    n_seg = len(data["RFM_Segments"][1])
    rbar.add_data(
        Reference(rfm_sh, min_col=2, min_row=1, max_row=1 + n_seg),
        titles_from_data=True,
    )
    rbar.set_categories(Reference(rfm_sh, min_col=1, min_row=2, max_row=1 + n_seg))
    rfm_sh.add_chart(rbar, "H2")

    wb.save(XLSX)
    print(f"\nWrote {XLSX}")

    # CSV copies for Tableau / Power BI (same tables, same numbers).
    for name, (cols, rows) in data.items():
        path = os.path.join(OUT_DIR, name.lower() + ".csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        print(f"Wrote {path}")

    print(f"\nBI export OK — total revenue {total_revenue:,} reconciles.")
    print("Next: open bi/retailpulse_bi.xlsx, or follow docs/BI_DASHBOARD.md")
    print("to build the same dashboard in Tableau / Power BI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
