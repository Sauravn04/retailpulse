# RetailPulse — End-to-End Retail Analytics Platform

RetailPulse is an end-to-end retail analytics platform that transforms raw retail transaction data into trusted business insights. It combines a **Bronze → Silver → Gold PostgreSQL warehouse**, SQL analytics, customer segmentation, revenue forecasting, and business intelligence dashboards in **Power BI and Excel**.

The project demonstrates both sides of an analytics workflow: building reliable data foundations and using the resulting data to answer business questions.

## Project at a glance

| Area | Result |
|---|---:|
| Source dataset | 12 tables, approximately 1 million rows |
| Orders | 300,000 |
| Order items | 600,000 |
| Products / stores / categories | 10,000 / 100 / 30 |
| Historical coverage | 1,462 days, 2020–2024 |
| Customers segmented with RFM | 49,751 |
| Champions | 8,184 |
| Hibernating customers | 11,234 |
| Reconciled revenue | 3,827,746,136 |
| Payment amount (reported separately) | 3,018,080,810 |
| Forecast baseline | 7-day rolling mean, 7.70% MAPE |

> **Data note:** The Kaggle dataset is synthetic and its category labels are anonymised (`Cat_1` to `Cat_30`). It is not a live point-of-sale feed. Revenue is calculated as `quantity × price`; payment totals are a separate measure and must not be treated as revenue.

## Business questions explored

RetailPulse uses SQL and BI reporting to investigate questions such as:

- How does revenue change over time?
- Which product categories contribute the most revenue?
- How do stores compare on sales performance?
- Which customer groups are most valuable, and which may need retention attention?
- What does a 30-day daily revenue forecast look like when evaluated against a time-based holdout?

### Selected findings

- RFM analysis segmented **49,751 customers**, including **8,184 Champions** and **11,234 Hibernating customers**.
- The five highest-revenue category IDs were **5, 3, 21, 26, and 12**. Category names are anonymised in the source dataset.
- The 7-day rolling-mean baseline achieved **7.70% MAPE**, outperforming Random Forest (**8.03%**) and Ridge regression (**7.86%**) on the evaluated holdout.
- Revenue reconciled to **3,827,746,136** across the Gold marts. Payment amount (**3,018,080,810**) was validated separately. The supplied real dataset produced **zero quarantined rows**.

## Architecture

![RetailPulse architecture](docs/images/architecture.png)

```mermaid
flowchart LR
    K["Kaggle CSVs<br/>12 tables · ~1M rows"] --> B["Bronze<br/>Raw values · TEXT"]
    B --> S["Silver<br/>Typed · cleaned · validated"]
    S --> G["Gold<br/>Daily · category · store<br/>Monthly · RFM · forecast"]
    G --> C["GCP Cloud SQL<br/>PostgreSQL 15 · asia-south1"]
    C --> P["Power BI dashboard"]
    G --> X["Excel workbook<br/>bi/retailpulse_bi.xlsx"]
```

**Data flow:** Kaggle CSVs → Bronze → Silver → Gold → GCP Cloud SQL → Power BI. The Excel workbook is also built from the Gold layer.

- **Bronze:** preserves the ingested source values in raw form.
- **Silver:** applies data typing, cleaning, primary-key rules, and quarantine handling.
- **Gold:** contains the analytical marts used by reporting and forecasting.

Gold is the reporting layer: BI and forecasting outputs are based on curated data rather than raw source files.

## Dashboard

The Power BI dashboard reads Gold data from **GCP Cloud SQL** and presents revenue, trends, category performance, store performance, customer segmentation, and forecasting.

Add the following PNG screenshots under `docs/images/` to display the dashboard previews in this section:

| Screenshot | File to add | Expected content |
|---|---|---|
| Full dashboard | `docs/images/dashboard-full.png` | Full report page and total revenue of 3,827,746,136 |
| Forecast | `docs/images/dashboard-forecast.png` | January 2024 forecast visual and 30-day total of 79,543,922 |
| Categories and RFM | `docs/images/dashboard-categories-rfm.png` | Category performance and RFM segments, including 11,234 Hibernating customers |

Once the image files are present, you can embed them here:

```markdown
![Full RetailPulse dashboard](docs/images/dashboard-full.png)
![January 2024 revenue forecast](docs/images/dashboard-forecast.png)
![Category performance and RFM segmentation](docs/images/dashboard-categories-rfm.png)
```

For details about the report and its visuals, see [`docs/BI_DASHBOARD.md`](docs/BI_DASHBOARD.md).

## Data warehouse and quality controls

The pipeline separates raw ingestion, cleaning, and analytical modelling into three layers:

| Layer | Purpose | Examples |
|---|---|---|
| Bronze | Raw landing layer | Source CSV values loaded into PostgreSQL as text |
| Silver | Cleaned and typed data | Validated records, keys, and quarantined rows |
| Gold | Analytics-ready marts | Daily, category, store, monthly, RFM, and forecast datasets |

Quality checks include source profiling, key and relationship checks, invalid-value detection, quarantine handling, and reconciliation between Silver and Gold. The revenue measure is consistently defined as `SUM(quantity × price)`. Payments are checked independently and are never added to revenue.

The reconciliation result for the supplied dataset is **3,827,746,136 in every Gold revenue mart**. The supplied run had **zero quarantined rows**; this is an observed result for this dataset, not an assumption built into the pipeline.

## SQL analytics and customer segmentation

SQL analysis includes joins, aggregations, ranking, and window functions such as rolling calculations and week-over-week comparisons.

RFM segmentation uses:

- **Recency:** how recently a customer made a purchase.
- **Frequency:** how often a customer purchased.
- **Monetary:** how much a customer spent.

The analysis assigned segments to 49,751 customers, including 8,184 Champions and 11,234 Hibernating customers. These segments can help a business identify high-value customers and groups that may benefit from retention campaigns.

## Revenue forecasting

The forecasting workflow creates lag and rolling-window features and evaluates models using a **time-based 30-day holdout**, rather than a random train/test split. This preserves the time order of the observations.

| Model | MAPE |
|---|---:|
| 7-day rolling-mean baseline | **7.70%** |
| Ridge regression | 7.86% |
| Random Forest | 8.03% |

The simple rolling-mean baseline performed best on the evaluated holdout, so it was retained as the reported result rather than presenting a more complex model as better. The 30-day January 2024 forecast total was **79,543,922**.

## Cloud deployment

The Gold layer was moved to **Google Cloud SQL (PostgreSQL 15, `asia-south1`)**, and Power BI was configured to read the curated data from Cloud SQL.

Connection details and deployment notes are documented in [`docs/CLOUD_SQL.md`](docs/CLOUD_SQL.md). Do not place database passwords, connection strings, service-account keys, or other credentials in this repository. Keep local secrets in `.env` and use an appropriate secrets-management method for hosted environments.

## Technology stack

| Category | Tools |
|---|---|
| Programming and data processing | Python |
| Database and querying | PostgreSQL 15, SQL, GCP Cloud SQL |
| Business intelligence | Power BI, Microsoft Excel |
| Data engineering | ETL, Bronze–Silver–Gold modelling, data-quality checks |
| Forecasting | Rolling-mean baseline, Ridge regression, Random Forest |
| Cloud | Google Cloud Platform |
| AI-assisted development | ChatGPT, Claude, Gemini |
| Development | Git, GitHub, VS Code |

Add libraries such as Pandas or NumPy to this list only if they are used by the project code.

## AI-assisted development

ChatGPT, Claude, and Gemini were used as development aids during the project, including support for SQL development, Python coding, debugging, exploring analytical approaches, and documentation.

AI-generated suggestions were treated as drafts rather than trusted results. Code and analytical outputs were reviewed against source data, business rules, SQL results, reconciliation checks, and the time-based forecasting evaluation before being accepted.

**Example of an AI output corrected during development:** Add a brief, specific example here before using this README as evidence of AI-assisted work. Describe what the AI suggested, how you checked it, what was wrong, and how you corrected it. Do not claim a correction unless it reflects an actual issue you encountered.

## Dataset

**Source:** [Kaggle — Retail Data Warehouse (12 Tables, 1M Rows)](https://www.kaggle.com/datasets/datarspectrum/retail-data-warehouse-12-table-1m-rows-dataset)

The project uses 12 source tables, including 300,000 orders, 600,000 order items, 10,000 products, 100 stores, and 30 anonymised categories. The core order data covers the stated 2020–2024 period (1,462 days).

Download the dataset from Kaggle and place the CSV files in `data/raw/`. See [`data/raw/README.md`](data/raw/README.md) for the expected local data setup. The raw dataset is not committed to this repository.

## Getting started

### Prerequisites

- Python 3.11 or later
- Git
- PostgreSQL 15
- VS Code or another code editor
- The Kaggle dataset downloaded locally

### 1. Clone the repository

```bash
git clone https://github.com/Sauravn04/retailpulse.git
cd retailpulse
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
```

**Windows PowerShell:**

```powershell
.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 4. Configure environment variables

Copy the example environment file and update it for your local PostgreSQL setup. Never commit the real `.env` file.

**Windows PowerShell:**

```powershell
Copy-Item .env.example .env
```

**macOS / Linux:**

```bash
cp .env.example .env
```

Set the local database URL in `.env` using your own credentials:

```env
DATABASE_URL=postgresql://retailpulse_user:YOUR_PASSWORD@localhost:5432/retailpulse
```

### 5. Create the local database

Connect to PostgreSQL as an administrator and run:

```sql
CREATE DATABASE retailpulse;
CREATE USER retailpulse_user WITH PASSWORD 'CHANGE_THIS_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE retailpulse TO retailpulse_user;
```

Then connect to the `retailpulse` database as an administrator and run:

```sql
GRANT USAGE, CREATE ON SCHEMA public TO retailpulse_user;
```

Use the same password in your local `.env` file. Replace the example password; do not reuse it.

### 6. Check the local setup

```bash
python scripts/check_setup.py
```

The setup check should report `SETUP OK` for Python, Git, and the required packages. PostgreSQL should be available before running the pipeline. If it is not running, the check may report that the database is down; start PostgreSQL before proceeding.

### 7. Download and profile the data

Place the Kaggle CSV files in `data/raw/`, then run:

```bash
python scripts/profile_data.py
```

The profiler discovers CSV files in `data/raw/`, checks the core tables and relationships, validates the stated date coverage, and compares revenue and payment totals separately. It writes `data/profile_report.json` and `docs/PROFILE.md`.

Continue with the schema and pipeline instructions in [`docs/DESIGN.md`](docs/DESIGN.md). Resolve any profiling failures before loading the data into the next warehouse layer.

## Repository structure

```text
retailpulse/
├── scripts/                 # Setup, profiling, pipeline, and validation scripts
├── sql/                     # Database schemas, transformations, analytics, and checks
├── data/
│   └── raw/                 # Local Kaggle CSVs (not committed)
├── bi/
│   ├── retailpulse_bi.xlsx  # Excel workbook
│   ├── retail_dashboard.pbix  # Power BI report
├── docs/
│   ├── images/              # Architecture and dashboard screenshots
│   ├── DESIGN.md             # Warehouse design
│   ├── PROFILE.md            # Generated profiling report
│   ├── BI_DASHBOARD.md       # Dashboard documentation
│   └── CLOUD_SQL.md          # Cloud SQL deployment notes
├── .env.example
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

## Project status

- [x] Repository, environment, and setup checks
- [x] Source data profiling and warehouse design
- [x] Bronze, Silver, and Gold pipeline
- [x] SQL analytics, RFM segmentation, and reconciliation checks
- [x] Excel workbook and Power BI dashboard
- [x] Time-based revenue forecasting and model comparison
- [x] Gold layer deployed to GCP Cloud SQL and connected to Power BI
- [ ] Add final dashboard screenshots to `docs/images/`
- [ ] Add a concrete, verified AI-correction example to this README

**Airflow is optional.** The core pipeline is implemented with Python and SQL and can run without Airflow. Airflow can be added later to orchestrate the same tasks; it does not replace the pipeline logic.

## Documentation

- [`docs/DESIGN.md`](docs/DESIGN.md) — Bronze, Silver, and Gold design
- [`docs/PROFILE.md`](docs/PROFILE.md) — data profiling output
- [`docs/BI_DASHBOARD.md`](docs/BI_DASHBOARD.md) — Power BI and Excel reporting
- [`docs/CLOUD_SQL.md`](docs/CLOUD_SQL.md) — GCP Cloud SQL deployment and connection notes
- [`data/raw/README.md`](data/raw/README.md) — raw dataset setup

## Important project assumptions

1. Revenue is calculated as `quantity × price`.
2. Payment amount is a separate measure and must not be mixed with revenue.
3. Forecast evaluation uses a time-based split, not a random split.
4. If a baseline outperforms a more complex model, report the baseline result honestly.
5. The source categories are anonymised, and the source dataset is synthetic.
6. Do not publish credentials, private connection details, or secrets in code, screenshots, or documentation.

---

**Author:** [Saurav Nayak](https://github.com/Sauravn04)
