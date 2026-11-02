# Step 8 (revised) — GCP Cloud SQL + Power BI to the cloud

Status: guide built 2 Nov 2026. **Not yet run** — Saurav needs
a GCP project with billing enabled first (his old project was
deleted 31 Oct 2026).

## What changes, and what does not
- **Changes:** the database moves from local Postgres to
  Cloud SQL (Postgres in GCP, region `asia-south1` / Mumbai).
  Power BI then reads from Cloud SQL, not from `127.0.0.1`.
- **Does not change:** the data, the numbers, or the
  dashboard. Gold is copied as-is; every total must match
  after the move, or the move failed.
- **Not deployed:** FastAPI / Cloud Run. The FastAPI code
  stays in the repo (`app/`, tests pass) as an optional
  extra, not a live service. Airflow is skipped.

## Cost — read this first
Cloud SQL Postgres has no permanent free tier. The smallest
instance is roughly $8–15/month plus storage — check the
exact price on the creation page, do not take that as a
quote. Charging starts as soon as the instance exists.
- Use the smallest tier, 10 GB storage only.
- Set a billing alert (step 2 below).
- Authorize only your own IP address, never 0.0.0.0/0.
- Delete the instance when you are done showcasing it:
  `gcloud sql instances delete retailpulse-db`
  (in Cloud Console: SQL → instance → Delete).

## Step 1 — GCP project (Console or gcloud)
Install gcloud if you do not have it, then:
```
gcloud auth login
gcloud config set project retailpulse-513512
# NOTE: the project NAME is "retailpulse" but the project ID
# is retailpulse-513512 — gcloud always needs the ID.
# If you create a new project instead, use its ID here.
gcloud services enable sqladmin.googleapis.com
```
If you already have a project, use its ID instead of
creating `retailpulse`, and set it with `gcloud config set`.

## Step 2 — Billing alert (Console)
Billing → Budgets & alerts → Create budget.
Project: retailpulse. Amount: $10. Alert at 100%.
This emails you if the cost reaches $10 — it does not
stop the instance, it only warns you.

## Step 3 — Create the Cloud SQL instance
```
gcloud sql instances create retailpulse-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=asia-south1 \
  --storage-size=10GB \
  --storage-type=SSD \
  --root-password='CHOOSE-A-STRONG-PASSWORD-HERE'
```
This takes a few minutes. Note the public IP it prints:
```
gcloud sql instances describe retailpulse-db \
  --format="value(ipAddresses[0].ipAddress)"
```

## Step 4 — Database, user, and your IP only
Find your public IP first (search "what is my ip"), then:
```
gcloud sql databases create retailpulse --instance=retailpulse-db
gcloud sql users create retailpulse_user --instance=retailpulse-db \
  --password='CHOOSE-A-DIFFERENT-STRONG-PASSWORD-HERE'
gcloud sql instances patch retailpulse-db \
  --authorized-networks=YOUR-HOME-IP/32
```
Never use `0.0.0.0/0` — that opens the database to the
whole internet. If your home IP changes, run the patch
command again with the new IP.

## Step 5 — Copy Gold (and Silver) from local Postgres
On your machine, in `D:\retailpulse`, with local Postgres
running. `CLOUD_URL` is the Cloud SQL connection string
— put it in a local file, never commit it:
```
set CLOUD_URL=postgresql://retailpulse_user:PASSWORD@CLOUD-SQL-IP:5432/retailpulse
python scripts/migrate_to_cloud.py
```
What that script does: `pg_dump` of the `silver`, `gold`,
`ops` and `quarantine` schemas from your local database,
`pg_restore` into Cloud SQL, then verifies counts and
revenue. Bronze is NOT copied — it is 1M raw rows, and
Gold is already built from it. If you ever need Bronze
in the cloud, rerun `load_bronze.py` against Cloud SQL
instead (slow, and it needs the CSVs).

## Step 6 — Verify on Cloud SQL (psql, before Power BI)
```
psql "postgresql://retailpulse_user:PASSWORD@CLOUD-SQL-IP:5432/retailpulse" -c "SELECT count(*) FROM gold.daily_sales;"
psql "postgresql://retailpulse_user:PASSWORD@CLOUD-SQL-IP:5432/retailpulse" -c "SELECT SUM(revenue) FROM gold.daily_sales;"
psql "postgresql://retailpulse_user:PASSWORD@CLOUD-SQL-IP:5432/retailpulse" -c "SELECT SUM(forecast) FROM gold.forecast_daily;"
```
Expected: 1,462 rows, 3,827,746,136, 79,543,922.
If any number differs, the copy failed — do not point
Power BI at it yet.

## Step 7 — Power BI: change the source, keep the visuals
1. Open `bi\retail_dashboard.pbix` in Power BI Desktop.
2. Home → Transform data → Data source settings →
   change the PostgreSQL server from `127.0.0.1` to the
   Cloud SQL public IP. Keep database `retailpulse`,
   user `retailpulse_user`, and enter the Cloud SQL
   password when asked.
3. Home → Refresh. Every visual should show the same
   numbers as before: Total Revenue 3,827,746,136,
   category 5 on top, Hibernating 11,234.
4. File → Save. The `.pbix` now reads from the cloud.
   Commit and push it to GitHub with the other Step 8
   files (see README).

If Refresh fails with a connection error, check step 4:
your IP in `--authorized-networks` must match the IP
Power BI is connecting from. Home Wi-Fi IPs change —
re-run the patch command with your current IP.

## Step 8 — Final GitHub push + LinkedIn
```
git add .
git status    # check: no .env, no data/raw/, no .venv
git commit -m "RetailPulse: Cloud SQL migration, Power BI reads from cloud"
git push
```
Then post on LinkedIn with a screenshot of the Power BI
dashboard and the GitHub link. Suggested numbers for the
post (all verified): 1M rows, 12 tables, Bronze → Silver
→ Gold, revenue 3,827,746,136, forecast 79,543,922 for
Jan 2024 with the rolling-mean baseline winning at
7.70% MAPE. Do not claim a live demo URL — there is
none; the dashboard is a Power BI file, not a website.
