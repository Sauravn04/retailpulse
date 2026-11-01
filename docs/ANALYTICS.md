# Step 4 — SQL analytics: what was built and how to read it

Status: built 1 Nov 2026, tested on real Postgres 16 (synthetic
full-count data, revenue tuned to 3,827,746,136). **Not yet run on
Saurav's real data** — run `python scripts/run_analytics.py` there.

## Files
- `sql/02_analytics.sql` — views + `gold.rfm_customers`
- `scripts/run_analytics.py` — applies the SQL, checks it, prints
  the headline answers, writes `data/analytics_report.json`

## Views (all in `gold.*`, read Gold only)
| View | Grain | What it answers |
|---|---|---|
| `v_daily_trend` | day | Revenue, 7d / 30d rolling avg, revenue 1d and 7d ago, WoW %, cumulative revenue |
| `v_monthly_trend` | month | Revenue, MoM %, 3-month rolling avg, cumulative revenue |
| `v_top_categories` | category | Total revenue, share %, RANK, cumulative share % |
| `v_top_stores` | store | Same shape as categories |

## RFM (`gold.rfm_customers`, one row per customer who ordered)
- Reference date = `MAX(order_date)` in Silver (2024-01-01 real).
- Recency = days since last order. Frequency = distinct orders.
  Monetary = `SUM(qty * price)`.
- Scores 1–5 by quintile (`NTILE(5)`): R high = recent, F high =
  frequent, M high = high spend.
- Segments (rule-based labels, not a model): Champions
  (R≥4, F≥4, M≥4), Loyal Customers (F≥4, M≥3), Potential
  Loyalists (R≥4, F≤3), At Risk (R≤2, F≥3), Hibernating
  (R≤2, F≤2), Needs Attention (R=3), Other.
- Customers with no orders are **not** in RFM; the run script
  reports how many there are (0 on the synthetic test).

## Two traps — read these before quoting a number
1. **January 2024 is a partial month.** `monthly_sales` has 49
   months, Jan 2020–Jan 2024, but Jan 2024 is only 1 day
   (2024-01-01). Its MoM % (about −97% on the synthetic run) is
   meaningless — do not quote it as a collapse. Compare Dec 2023
   with Nov 2023 for the last real MoM.
2. **First 6 days have a partial 7d window.** `rolling_7d_revenue`
   for 2020-01-01 to 2020-01-06 averages only the days available
   so far. That is honest, not hidden, but don't compare a
   1-day average with a 7-day one.

## Checks (`run_analytics.py`, exit 0 = PASS)
Views row counts (1,462 / 30 / 100 / 49), revenue in
`v_top_categories` / `v_top_stores` / cumulative daily trend /
RFM monetary all = 3,827,746,136, RFM scores all 1–5.
