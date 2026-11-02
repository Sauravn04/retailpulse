# Step 6 — Forecasting: what it does and how to read it

Status: built 2 Nov 2026, tested in CSV mode on synthetic
daily data (see below). **Not yet run on Saurav's real data**
— run `python scripts/forecast.py` there.

## What it forecasts
Daily revenue for the next 30 days: 2024-01-02 to 2024-01-31.
It reads `gold.daily_sales` only (1,462 days).

## How it works, in plain language
1. **Features.** For each day, the model looks at: revenue
   1, 7, 14 and 30 days ago, the average of the last 7 and
   30 days, the day of the week, and the month. No future
   data is ever used to predict a day — every feature comes
   from *before* that day.
2. **Time-based holdout (never random).** Train on all but
   the last 30 days, test on the last 30 days
   (2023-12-03 to 2024-01-01). Random splitting would leak
   the future into training and make the score look better
   than it is.
3. **Three models, same holdout, one-step-ahead.**
   RandomForest, Ridge regression, and a rolling-mean-7
   baseline (predict tomorrow's revenue as the average of
   the last 7 days). All three are scored with MAE / RMSE /
   MAPE on numpy arrays — not pandas indexes, because that
   silent misalignment gave a wrong MAPE in the old project.
4. **Best model wins, even if it's the baseline.** The
   winner is refit on all 1,462 days and forecasts the
   next 30 days one day at a time, feeding each forecast
   back in as the next day's lag. In the old project the
   baseline won (MAPE 7.70% vs RandomForest 8.11%) — if
   that happens again here, the forecast IS the baseline,
   and that is reported, not hidden.
5. **Uncertainty.** Forecast +/- 1.96 x the winner's
   holdout RMSE, clipped at zero. That is an interval
   (about 95% if errors were normal), not a promise.

## Outputs
- `data/forecast.csv` — 30 rows: date, forecast, lower, upper, model
- `data/forecast_metrics.json` — holdout metrics for all three
  models, best model, forecast total and mean daily
- `gold.forecast_daily` in Postgres — same 30 rows, for Step 7

## Synthetic test (this VM, 2 Nov 2026)
Synthetic daily series, mean ~2.5M/day:
RandomForest MAPE 6.23%, Ridge 6.77%, rolling-mean-7 7.81%.
Best: RandomForest. Forecast total 76,826,789, mean
2,560,893/day, interval +/- 421,404. These are synthetic
numbers — Saurav's real numbers will differ, and the best
model may differ too.

## Traps
- A low MAPE on the holdout does not mean the next 30 days
  will be that accurate — the holdout is the past, the
  forecast is the future.
- The last real day is 2024-01-01. Do not "forecast" it —
  it is already in the data.
- Do not compare MAPE across different holdouts. The old
  project's 8.11% was on the same last-30-days holdout,
  so it is comparable; a random split would not be.
