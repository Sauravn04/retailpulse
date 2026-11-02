"""Step 6 — Forecast daily revenue for the next 30 days.

Run:  python scripts/forecast.py
       python scripts/forecast.py --csv data/daily_sales.csv   (test only)
What it does
------------
* Reads gold.daily_sales (1,462 days, 2020-01-01 to 2024-01-01)
  from Postgres. Never reads Bronze or CSVs in normal use.
* Builds lag / rolling features: lag_1, lag_7, lag_14, lag_30,
  rolling 7-day and 30-day means, day-of-week, month.
* Time-based holdout (never random): train on all but the last
  30 days, test on the last 30 days (2023-12-03 to 2024-01-01).
* Compares three models on the SAME holdout, one-step-ahead:
  RandomForest, Ridge regression, and a rolling-mean-7 baseline.
  Metrics are MAE / RMSE / MAPE, computed on numpy arrays
  (never on pandas indexes — that silent misalignment gave a
  wrong MAPE in the old project).
* Refits the BEST holdout model on all 1,462 days and forecasts
  the next 30 days (2024-01-02 to 2024-01-31) recursively.
  If the baseline wins, the forecast IS the baseline — that is
  reported, not hidden.
* Uncertainty: forecast +/- 1.96 * holdout RMSE of the chosen
  model, clipped at zero. That is an interval, not a promise.
Writes: data/forecast.csv, data/forecast_metrics.json,
  and gold.forecast_daily in Postgres (DROP + CREATE).
Needs: DATABASE_URL in .env, Postgres running, Step 3b done.
Exit 0 = forecast written. There is no PASS/FAIL here — a bad
  MAPE is a finding, reported honestly, not a failed run.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

HOLDOUT_DAYS = 30
FORECAST_DAYS = 30
FEATURES = ["lag_1", "lag_7", "lag_14", "lag_30",
            "roll_7", "roll_30", "dow", "month"]


def load_daily(csv_path=None):
    import pandas as pd

    if csv_path:
        df = pd.read_csv(csv_path, parse_dates=["order_date"])
    else:
        import psycopg2

        url = os.getenv("DATABASE_URL", "")
        if not url:
            raise SystemExit("[FAIL] DATABASE_URL not set")
        conn = psycopg2.connect(url)
        try:
            df = pd.read_sql(
                "SELECT order_date, revenue FROM gold.daily_sales "
                "ORDER BY order_date", conn, parse_dates=["order_date"])
        finally:
            conn.close()
    df = df.sort_values("order_date").reset_index(drop=True)
    return df


def make_features(df):
    """Add lag/rolling features. First 30 rows have NaNs — dropped."""
    import pandas as pd

    df = df.copy()
    rev = df["revenue"]
    df["lag_1"] = rev.shift(1)
    df["lag_7"] = rev.shift(7)
    df["lag_14"] = rev.shift(14)
    df["lag_30"] = rev.shift(30)
    df["roll_7"] = rev.shift(1).rolling(7).mean()
    df["roll_30"] = rev.shift(1).rolling(30).mean()
    df["dow"] = df["order_date"].dt.dayofweek
    df["month"] = df["order_date"].dt.month
    return df


def metrics(y_true, y_pred):
    import numpy as np

    # Numpy arrays, not pandas Series — index alignment silently
    # produced NaNs (and a wrong MAPE) in the old project.
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    err = y_true - y_pred
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mape = float(np.mean(np.abs(err) / np.maximum(y_true, 1e-9)) * 100)
    return {"mae": round(mae, 2), "rmse": round(rmse, 2),
            "mape": round(mape, 2)}


def main() -> int:
    import numpy as np
    import pandas as pd
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None,
                    help="Test only: read daily sales from this CSV "
                    "instead of Postgres.")
    args = ap.parse_args()

    df = load_daily(args.csv)
    print(f"Daily sales: {len(df):,} rows, "
          f"{df['order_date'].min().date()} to "
          f"{df['order_date'].max().date()}")
    if len(df) != 1462:
        print(f"[WARN] expected 1,462 days, got {len(df):,} — "
              "continuing, but check Step 3b.")
    gaps = df["order_date"].diff().dt.days.dropna()
    if (gaps != 1).any():
        print(f"[WARN] {(gaps != 1).sum()} missing day(s) in daily_sales.")

    feat = make_features(df).dropna(subset=FEATURES).reset_index(drop=True)
    # Time-based holdout: last 30 days are the test set.
    test = feat.tail(HOLDOUT_DAYS)
    train = feat.iloc[:-HOLDOUT_DAYS]
    print(f"Train: {len(train):,} days to {train['order_date'].max().date()}, "
          f"holdout: {len(test):,} days from "
          f"{test['order_date'].min().date()}")

    X_train = train[FEATURES].to_numpy()
    y_train = train["revenue"].to_numpy()
    X_test = test[FEATURES].to_numpy()
    y_test = test["revenue"].to_numpy()

    models = {
        "random_forest": RandomForestRegressor(
            n_estimators=200, random_state=42, n_jobs=-1),
        "ridge": make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "rolling_mean_7": None,  # baseline, no fitting
    }
    results = {}
    for name, model in models.items():
        if name == "rolling_mean_7":
            # One-step-ahead: mean of the previous 7 ACTUAL days.
            pred = test["roll_7"].to_numpy()
        else:
            model.fit(X_train, y_train)
            pred = model.predict(X_test)
        results[name] = metrics(y_test, pred)
        m = results[name]
        print(f"  {name}: MAE {m['mae']:,.0f}, RMSE {m['rmse']:,.0f}, "
              f"MAPE {m['mape']:.2f}%")

    best = min(results, key=lambda k: results[k]["mape"])
    print(f"\nBest on holdout (lowest MAPE): {best} "
          f"({results[best]['mape']:.2f}%)")
    if best == "rolling_mean_7":
        print("The simple baseline beat both ML models on this holdout. "
              "That is the honest result — the forecast below uses it.")
    best_rmse = results[best]["rmse"]

    # Refit the winner on ALL data, then forecast 30 days recursively.
    full = feat
    X_full = full[FEATURES].to_numpy()
    y_full = full["revenue"].to_numpy()
    history = list(df["revenue"].to_numpy())
    last_date = df["order_date"].max()
    model = models[best]
    if model is not None:
        model.fit(X_full, y_full)

    forecasts = []
    for i in range(FORECAST_DAYS):
        hist = np.asarray(history, dtype=float)
        row = {
            "lag_1": hist[-1], "lag_7": hist[-7], "lag_14": hist[-14],
            "lag_30": hist[-30], "roll_7": hist[-7:].mean(),
            "roll_30": hist[-30:].mean(),
            "dow": (last_date + pd.Timedelta(days=i + 1)).dayofweek,
            "month": (last_date + pd.Timedelta(days=i + 1)).month,
        }
        if best == "rolling_mean_7":
            pred = float(row["roll_7"])
        else:
            pred = float(model.predict(
                np.array([[row[f] for f in FEATURES]]))[0])
        pred = max(pred, 0.0)
        history.append(pred)
        day = last_date + pd.Timedelta(days=i + 1)
        forecasts.append({
            "order_date": day.date().isoformat(),
            "forecast": round(pred, 2),
            "lower": round(max(pred - 1.96 * best_rmse, 0.0), 2),
            "upper": round(pred + 1.96 * best_rmse, 2),
            "model": best,
        })

    total = sum(f["forecast"] for f in forecasts)
    print(f"\nForecast {forecasts[0]['order_date']} to "
          f"{forecasts[-1]['order_date']} ({best}): "
          f"total {total:,.0f}, mean {total / FORECAST_DAYS:,.0f}/day")
    print(f"Interval: +/- {1.96 * best_rmse:,.0f} (1.96 x holdout RMSE)")

    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "forecast.csv"), "w",
              newline="", encoding="utf-8") as f:
        import csv

        w = csv.DictWriter(f, fieldnames=["order_date", "forecast",
                                          "lower", "upper", "model"])
        w.writeheader()
        w.writerows(forecasts)
    payload = {"holdout_days": HOLDOUT_DAYS,
               "holdout_from": str(test["order_date"].min().date()),
               "holdout_to": str(test["order_date"].max().date()),
               "models": results, "best_model": best,
               "forecast_from": forecasts[0]["order_date"],
               "forecast_to": forecasts[-1]["order_date"],
               "forecast_total": round(total, 2),
               "forecast_mean_daily": round(total / FORECAST_DAYS, 2),
               "interval_half_width": round(1.96 * best_rmse, 2)}
    with open(os.path.join(ROOT, "data", "forecast_metrics.json"),
              "w") as f:
        json.dump(payload, f, indent=2)
    print("Wrote data/forecast.csv and data/forecast_metrics.json")

    if not args.csv:
        import psycopg2

        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        try:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS gold.forecast_daily")
                cur.execute(
                    "CREATE TABLE gold.forecast_daily ("
                    "order_date DATE PRIMARY KEY, forecast NUMERIC(14,2), "
                    "lower_bound NUMERIC(14,2), upper_bound NUMERIC(14,2), "
                    "model TEXT)")
                for f in forecasts:
                    cur.execute(
                        "INSERT INTO gold.forecast_daily VALUES "
                        "(%s, %s, %s, %s, %s)",
                        (f["order_date"], f["forecast"], f["lower"],
                         f["upper"], f["model"]))
            conn.commit()
        finally:
            conn.close()
        print("Wrote gold.forecast_daily (30 rows) in Postgres.")
    else:
        print("CSV test mode: gold.forecast_daily NOT written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
