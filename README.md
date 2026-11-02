# RetailPulse — End-to-End Retail Data Platform

> **Fresh build, from scratch.** One project, two stories:
> analytics (SQL, BI, forecasting) and data engineering (pipeline, warehouse, quality).
> Built step by step. Do not skip a step's checkpoint.

## Architecture

```mermaid
flowchart LR
    K[Kaggle CSVs<br/>12 tables, ~1M rows] --> B[Bronze<br/>PostgreSQL, all TEXT]
    B --> S[Silver<br/>typed, PKs, quarantine]
    S --> G[Gold<br/>daily / category / store<br/>monthly + RFM + forecast]
    G --> C[GCP Cloud SQL<br/>Postgres 15, asia-south1]
    C --> P[Power BI<br/>dashboard]
    G --> X[Excel workbook<br/>bi/retailpulse_bi.xlsx]
```

Kaggle → Bronze → Silver → Gold → Cloud SQL → Power BI.
Bronze is raw, Silver is cleaned, Gold is the only layer
BI and forecasting read from.

## Dashboard

Screenshots live in `docs/images/` — put yours there with
exactly these names, then they show up here automatically:

| Screenshot | File | What it must show |
|---|---|---|
| Full dashboard | `docs/images/dashboard-full.png` | All 5 visuals, Total Revenue 3,827,746,136 |
| Forecast visual | `docs/images/dashboard-forecast.png` | Forecast line, Jan 2024, total 79,543,922 |
| Categories + RFM | `docs/images/dashboard-categories-rfm.png` | Category 5 on top, Hibernating 11,234 on top |

![Full dashboard](docs/images/dashboard-full.png)

![Forecast, Jan 2024](docs/images/dashboard-forecast.png)

![Top categories and RFM](docs/images/dashboard-categories-rfm.png)

> How to take them: in Power BI Desktop, after Refresh from
> Cloud SQL, use Snipping Tool on the dashboard page —
> one screenshot of the whole page, one zoomed on the
> forecast visual, one zoomed on the category + RFM charts.
> Save as PNG, not JPG, so the numbers stay readable.

## The idea

A retailer cannot plan stock if it cannot trust its numbers.
RetailPulse turns the Kaggle Retail Data Warehouse (12 tables, ~1M rows)
into trusted Bronze → Silver → Gold tables in PostgreSQL,
answers business questions in SQL and BI,
and forecasts daily revenue for the next 30 days.

- **Dataset:** Kaggle — Retail Data Warehouse, datarspectrum
  https://www.kaggle.com/datasets/datarspectrum/retail-data-warehouse-12-table-1m-rows-dataset
  300,000 orders, 600,000 order items, 30 categories, 100 stores,
  10,000 products, 1,462 days (2020-01-01 to 2024-01-01).
  Revenue is always qty × price. Total revenue, verified here in Step 3
  on the real data: 3,827,746,136 (every Gold mart, 0 quarantined).
  Payments total (3,018,080,810) does NOT equal revenue — never mix them.
  Categories are anonymised (Cat_1..Cat_30). This is synthetic data,
  not a live POS feed. Say so in interviews.

## What you will be able to show at the end

- A Postgres warehouse: Bronze (raw) → Silver (cleaned) → Gold (marts)
- A pipeline you can rerun safely, with a run log and data-quality gates
- SQL analytics with window functions, ranking, and RFM
- An Excel workbook + a Tableau / Power BI dashboard
- A forecast with honest holdout metrics (time-based split, baselines included)
- Gold in GCP Cloud SQL, with Power BI reading from the cloud
- A GitHub repo, a 2-minute Loom, and resume bullets with real numbers

## Build plan (one step at a time)

- [x] **Step 1 — Setup:** repo, venv, folders, setup check.
- [x] **Step 2 — Explore + design:** PROFILE PASS, 0 checks failed, on real Kaggle data.
- [x] **Step 3 — Pipeline:** Bronze 12/12 OK, Silver + Gold OK, revenue reconciles
  to 3,827,746,136 in every mart, payments 3,018,080,810, 0 quarantined.
- [x] **Step 4 — SQL analytics + quality:** window functions, RFM, reconciliation PASS.
  Top categories 5, 3, 21, 26, 12; Champions 8,184, Hibernating 11,234.
- [x] **Step 5 — BI:** Excel workbook (`bi/retailpulse_bi.xlsx`) + Power BI dashboard
  (`bi/retail_dashboard.pbix`) + Power BI reading from Cloud SQL — see `docs/BI_DASHBOARD.md`.
- [x] **Step 6 — Forecasting:** lag/rolling features, time holdout, baselines.
  Rolling-mean-7 MAPE 7.70% beat RandomForest 8.03% / Ridge 7.86%;
  30-day forecast total 79,543,922.
- [x] **Step 8 — GCP Cloud SQL (revised 2 Nov, complete 3 Nov):** Gold moved
  to Cloud SQL (35.200.179.31, project retailpulse-513512) and Power BI
  reads from it — see `docs/CLOUD_SQL.md`. Replaces the original
  Cloud Run deploy plan.

Airflow is **optional, Step 3b, not required** to finish the project.
The core pipeline is Python + SQL, runnable without Airflow.
If we add Airflow later, it will orchestrate the same Python/SQL tasks —
it will not replace them. GitHub push is also Step 8, at the end.

## Step 1 — Setup (do this now, on your machine)

You need: VS Code, Python 3.11+, Git, PostgreSQL 15 (local system).
You already have Python and Git installed.

```bash
# 1. Open this folder in VS Code
# 2. Create and activate a virtual environment
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 4. Copy the example env file (never commit the real .env)
copy .env.example .env
# macOS / Linux: cp .env.example .env
# Edit .env only to match YOUR local Postgres password.

# 5. Run the setup check
python scripts/check_setup.py
```

Done when `check_setup.py` prints `SETUP OK` for Python, Git and
packages, and Postgres shows `up` (or a clear `down — Step 3 will
need it` warning if Postgres is not running yet).

## Step 2 — Explore + design (prepared, run it on your machine)

No Postgres needed for this step — it only reads the CSVs.

```bash
# 1. Download the Kaggle dataset into data/raw/ (see data/raw/README.md)
# 2. Run the profiler
python scripts/profile_data.py
```

It discovers every `*.csv` in `data/raw/` (it does not assume the
12 file names), then checks the 7 core tables, the orders date range
(1,462 days, 2020-01-01 to 2024-01-01), the joins, revenue
`SUM(qty * price)` against 3,827,746,136, and payments
`SUM(amount)` against 3,018,080,810 — kept separate, never mixed.
It writes `data/profile_report.json` and `docs/PROFILE.md`.

`docs/DESIGN.md` is the Bronze → Silver → Gold design draft to
confirm against that profile. The 5 Kaggle tables beyond the 7 core
ones are deliberately **not** given a Silver design yet — the
profiler output decides what they are first.

Step 2 is done when the profiler prints `PROFILE PASS`. Any FAIL is
a finding to record in `docs/DESIGN.md` before Step 3, not something
to load around.

## Local database (Step 3 will use this)

```sql
-- In psql, as the postgres superuser:
CREATE DATABASE retailpulse;
CREATE USER retailpulse_user WITH PASSWORD 'CHANGE-ME';
GRANT ALL PRIVILEGES ON DATABASE retailpulse TO retailpulse_user;
-- Then, connected to retailpulse as postgres:
GRANT USAGE, CREATE ON SCHEMA public TO retailpulse_user;
```

`.env` for local work:
`DATABASE_URL=postgresql://retailpulse_user:CHANGE-ME@localhost:5432/retailpulse`

## Project structure

```
retailpulse/
├── scripts/        # Pipeline + checks (Steps 1-6)
│   └── check_setup.py
├── sql/            # Schema, analytics, quality checks (Steps 2-4)
├── data/
│   └── raw/        # Kaggle CSVs go here — NEVER committed (see data/raw/README.md)
├── docs/           # Setup + design notes
├── .env.example
├── requirements.txt
└── README.md
```

## Rules for this build

1. No number goes in the README until a script has verified it.
2. Revenue is qty × price, always. Payments are a separate total.
3. Train/test split is by time, never random.
4. If a baseline beats the model, report it. Do not hide it.
5. No live URL, no GitHub link, until it actually works.
