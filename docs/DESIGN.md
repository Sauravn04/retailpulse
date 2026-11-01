# Step 2 — Warehouse design (Bronze → Silver → Gold)

Status: **CONFIRMED 1 Nov 2026 — PROFILE PASS, 0 checks failed, on Saurav's
fresh Kaggle download.** All expected numbers re-verified here:
categories 30, stores 100, products 10,000, orders 300,000,
order_items 600,000, 1,462 days 2020-01-01 to 2024-01-01, 0 missing days,
0 unmatched order items, revenue SUM(qty*price) = 3,827,746,136,
payments SUM = 3,018,080,810 (different total, never mixed).
Extra tables (Bronze only for now): customers 50,000, employees 1,000,
promotions 50, returns 30,000, shipments 300,000, suppliers 200.
All 12 files: 0 nulls, 0 duplicate rows.

Dataset: Kaggle Retail Data Warehouse (datarspectrum),
https://www.kaggle.com/datasets/datarspectrum/retail-data-warehouse-12-table-1m-rows-dataset
— 12 tables, ~1M rows. Synthetic, anonymised data, not a live POS feed.

## What the profiler must answer first

Run `python scripts/profile_data.py` (no Postgres needed). It writes
`data/profile_report.json` and `docs/PROFILE.md`. Step 2 is done when:

- All 12 CSVs are listed in the profile, with row counts, columns,
  nulls and duplicate rows — including the 5 tables beyond the 7 core
  ones below. Their columns are **not guessed here**; the profiler
  output decides what they are and whether Step 3 loads them.
- The 7 core tables match the expected counts, or the mismatch is
  recorded as a finding: categories 30, stores 100, products 10,000,
  orders 300,000, order_items 600,000.
- Orders cover 1,462 distinct days, 2020-01-01 to 2024-01-01, no gaps.
- Revenue `SUM(qty * price)` = 3,827,746,136 (old-project verified).
- Payments `SUM(amount)` = 3,018,080,810 (old-project verified) —
  a different total, kept separate, never mixed into revenue.

## Bronze — raw, as downloaded

Schema `bronze`, one table per CSV, columns exactly as in the file
(all text/numeric as read, no cleaning, no dropped rows), plus:

- `_source_file TEXT` — which CSV the row came from
- `_loaded_at TIMESTAMPTZ` — when Step 3 loaded it

Bronze is the audit trail: if Silver ever looks wrong, Bronze is
where you prove what the source actually said. Nothing is deleted
from Bronze in Step 3; a rerun replaces a file's rows, never appends
a second copy (see `pipeline_runs` in Step 3).

## Silver — cleaned, typed, joined

Schema `silver`. The 7 core tables, types/PKs/FKs taken from the
old project's verified DDL (`sql/01_schema.sql` in the v2 reference),
adapted to the `silver` schema:

| Table | Grain | Key columns |
|---|---|---|
| `silver.categories` | one row per category | `category_id INT PK`, `category_name TEXT` — 30 rows, Cat_1..Cat_30, no real names |
| `silver.stores` | one row per store | `store_id INT PK`, `city TEXT` — 100 rows; cities Mumbai, Pune, Delhi, Bangalore only |
| `silver.products` | one row per product | `product_id INT PK`, `category_id INT → categories`, `price NUMERIC(12,2) CHECK >= 0` — 10,000 rows, no product names |
| `silver.customers` | one row per customer | `customer_id INT PK`, `city TEXT`, `signup_date DATE` |
| `silver.orders` | one row per order | `order_id INT PK`, `customer_id INT → customers`, `store_id INT → stores`, `order_date DATE NOT NULL` — 300,000 rows |
| `silver.order_items` | one row per order line | `order_item_id INT PK`, `order_id INT → orders`, `product_id INT → products`, `qty INT CHECK > 0`, `price NUMERIC(12,2) CHECK >= 0` — 600,000 rows |
| `silver.payments` | one row per payment | `payment_id INT PK`, `order_id INT → orders`, `amount NUMERIC(14,2)`, `payment_date DATE` — reconciliation only |

Cleaning rules (Step 3 implements these; the profiler only reports):

- Deduplicate on the primary key; duplicates go to a quarantine
  table, they are not silently dropped.
- Null keys, `qty <= 0`, `price < 0` → quarantine, not Silver.
- Unmatched `order_id` / `product_id` in order_items → quarantine.
  Expected (old project): 0 unmatched — verify, don't assume.
- Payments are loaded but **never** joined into revenue. The
  payments-vs-revenue gap is a documented data-quality finding.

The other 5 Kaggle tables: load into Bronze only, for now.
Promote one to Silver only if the profile shows it has a clean key
and a real use in a business question (Step 4) or a Gold mart
(Step 3). Do not invent a Silver table for a file you haven't read.

## Gold — marts people actually query

Schema `gold`, rebuilt from Silver only (never from Bronze or CSVs):

| Table | Grain | Definition |
|---|---|---|
| `gold.daily_sales` | one row per day | `order_date DATE PK`, `revenue = SUM(qty*price)`, `quantity`, `orders` — 1,462 rows |
| `gold.daily_category_sales` | day × category | `order_date, category_id PK`, `revenue`, `quantity` — 43,860 rows (1,462 × 30) |
| `gold.daily_store_sales` | day × store | `order_date, store_id PK`, `revenue`, `quantity` |
| `gold.monthly_sales` | month | `month DATE PK`, `revenue`, `quantity`, `orders` |
| `gold.rfm_customers` | one row per customer | recency / frequency / monetary from `silver.orders` + `silver.order_items`, built in Step 4 |

Reconciliation gate (Step 3/4): Gold totals must equal Silver
totals must equal `SUM(qty * price)` = 3,827,746,136, in all three
marts. If they disagree, Gold does not rebuild — fix Silver first.

## Loading rules (Step 3, preview)

- `COPY` (or `pandas.to_sql` with chunks) for the 600k order_items,
  not row-by-row inserts.
- Indexes are created **after** the load, not before.
- Incremental loads keyed on `order_date` where possible; a rerun
  of the same file creates zero duplicates (verified by re-running
  the load and re-checking row counts).
- Every run writes one row to `pipeline_runs` (file, rows loaded,
  bad rows quarantined, time taken, status).

## Business questions this design must support (Step 4)

1. Which categories and stores drive revenue, and by how much?
2. Is revenue growing week-over-week and month-over-month?
3. Which customers are recent, frequent, high-value — who is going quiet?
4. What will daily revenue be for the next 30 days, and how uncertain is it?
5. Where is the data not trustworthy, and what did we do about it?

If a table in this design serves none of those questions, it is
out of scope for v1 — say so, don't build it anyway.

## Decisions already made (do not reopen without Saurav)

- Airflow is optional, Step 3b only. Core pipeline is Python + SQL.
- GitHub push is Step 8, at the end — not after Step 2.
- No live GCP URL, no GitHub link, until it actually works.
- No number goes in the README until a script has verified it here.
