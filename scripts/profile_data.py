"""Step 2 — Profile the Kaggle CSVs in data/raw/ (no Postgres needed).

Run from the project root, after downloading the Kaggle dataset
into data/raw/ (see data/raw/README.md):

    python scripts/profile_data.py

What it does
------------
* Discovers every *.csv in data/raw/ — it does NOT assume the
  12 file names. Extra / missing files are reported, not hidden.
* For each file: rows, columns, dtypes, null counts, duplicate
  full rows, and min/max for numeric and date-like columns.
* For the 7 core tables (categories, stores, products, customers,
  orders, order_items, payments) it runs the cross-file checks
  that Step 2 must answer before Step 3 loads anything:
    - orders date range, distinct days, missing days
    - order_items join to orders / products (unmatched rows)
    - revenue = SUM(qty * price), expected 3,827,746,136
      (verified in the old project; re-verify here, do not copy
      the number into the README until this script passes)
    - payments SUM(amount), expected 3,018,080,810 — a DIFFERENT
      total, kept separate from revenue, never mixed in
    - row counts: categories 30, stores 100, products 10,000,
      orders 300,000, order_items 600,000 (expected; reported
      as actual vs expected, a mismatch is a finding, not a crash)

Outputs (both are regenerated on every run)
-------------------------------------------
* data/profile_report.json  — full machine-readable report
  (gitignored: data/*.json — local only, rebuildable)
* docs/PROFILE.md           — human-readable summary, committed
  to the repo so the design decisions in docs/DESIGN.md can be
  traced back to the actual files on disk.

Exit code: 0 if every file could be read and every cross-file
check that had its inputs present passed; 1 otherwise.
A missing core file is a FAIL — download the full Kaggle set
before running Step 3.
"""

import json
import os
import sys
from datetime import datetime

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")
JSON_OUT = os.path.join(ROOT, "data", "profile_report.json")
MD_OUT = os.path.join(ROOT, "docs", "PROFILE.md")

# Expected values from the old project (v2, verified 31 Oct 2026).
# They are EXPECTATIONS here, not RetailPulse results — this script
# is what re-verifies them on the fresh download.
EXPECTED = {
    "categories": 30,
    "stores": 100,
    "products": 10_000,
    "orders": 300_000,
    "order_items": 600_000,
}
EXPECTED_REVENUE = 3_827_746_136
EXPECTED_PAYMENTS = 3_018_080_810
EXPECTED_DAYS = 1_462
EXPECTED_DATE_MIN = "2020-01-01"
EXPECTED_DATE_MAX = "2024-01-01"

CORE_FILES = [
    "categories",
    "stores",
    "products",
    "customers",
    "orders",
    "order_items",
    "payments",
]


def _profile_one(path):
    """Profile one CSV file; returns (summary dict, DataFrame or None)."""
    name = os.path.splitext(os.path.basename(path))[0]
    df = pd.read_csv(path, low_memory=False)
    cols = {}
    for col in df.columns:
        s = df[col]
        info = {
            "dtype": str(s.dtype),
            "nulls": int(s.isna().sum()),
            "null_pct": round(float(s.isna().mean() * 100), 2),
            "unique": int(s.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(s):
            info["min"] = s.min().item() if not s.isna().all() else None
            info["max"] = s.max().item() if not s.isna().all() else None
            # JSON-safe: numpy scalars -> python scalars
            for k in ("min", "max"):
                v = info[k]
                info[k] = v.item() if hasattr(v, "item") else v
        cols[col] = info
    summary = {
        "file": os.path.basename(path),
        "rows": int(len(df)),
        "columns": list(df.columns),
        "column_count": int(len(df.columns)),
        "duplicate_full_rows": int(df.duplicated().sum()),
        "null_total": int(df.isna().sum().sum()),
        "columns_detail": cols,
    }
    return summary, df


def _check(results, name, passed, actual, expected, note=""):
    results.append(
        {
            "check": name,
            "status": "PASS" if passed else "FAIL",
            "actual": actual,
            "expected": expected,
            "note": note,
        }
    )
    print(
        f"  [{'PASS' if passed else 'FAIL'}] {name}: "
        f"actual={actual} expected={expected} {note}"
    )


def main():
    print("RetailPulse — Step 2 profile")
    print(f"Reading CSVs from {RAW_DIR}/")
    if not os.path.isdir(RAW_DIR):
        print(
            f"[FAIL] {RAW_DIR} does not exist — download the Kaggle "
            "dataset first (see data/raw/README.md)."
        )
        return 1

    files = sorted(f for f in os.listdir(RAW_DIR) if f.lower().endswith(".csv"))
    if not files:
        print(
            "[FAIL] No CSVs in data/raw/ — download the Kaggle "
            "dataset first (see data/raw/README.md)."
        )
        return 1

    print(f"Found {len(files)} CSV file(s): {', '.join(files)}")
    tables = {}
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "files": {},
        "checks": [],
    }
    ok = True

    for fname in files:
        summary, df = _profile_one(os.path.join(RAW_DIR, fname))
        name = os.path.splitext(fname)[0]
        tables[name] = df
        report["files"][name] = summary
        print(
            f"  {fname}: {summary['rows']:,} rows, "
            f"{summary['column_count']} cols, "
            f"{summary['null_total']:,} nulls, "
            f"{summary['duplicate_full_rows']:,} duplicate rows"
        )

    # --- Missing / extra files -------------------------------------------
    present = set(tables)
    missing = [c for c in CORE_FILES if c not in present]
    extra = sorted(present - set(CORE_FILES))
    print("\nCore-file check:")
    _check(
        report["checks"],
        "core_files_present",
        not missing,
        f"{len(CORE_FILES) - len(missing)}/{len(CORE_FILES)} present",
        "all 7 core files",
        f"missing: {missing}" if missing else "",
    )
    if extra:
        print(
            f"  [INFO] Extra file(s) beyond the 7 core tables: {extra} "
            "— these are the remaining Kaggle tables. "
            "Record their columns in docs/DESIGN.md; do not invent "
            "a use for them until profiled."
        )
    if missing:
        ok = False

    # --- Expected row counts ----------------------------------------------
    print("\nRow-count check (expected = old project, verified):")
    for table, expected in EXPECTED.items():
        if table not in tables:
            continue
        actual = len(tables[table])
        passed = actual == expected
        if not passed:
            ok = False
        _check(report["checks"], f"rows_{table}", passed, actual, expected)

    # --- Orders: date range / continuity ----------------------------------
    if "orders" in tables and "order_date" in tables["orders"].columns:
        print("\nOrders date check:")
        dates = pd.to_datetime(tables["orders"]["order_date"], errors="coerce")
        dmin, dmax = dates.min(), dates.max()
        ndays = int(dates.dt.date.nunique())
        span = (dmax - dmin).days + 1 if pd.notna(dmin) and pd.notna(dmax) else None
        _check(
            report["checks"],
            "orders_date_range",
            str(dmin.date()) == EXPECTED_DATE_MIN
            and str(dmax.date()) == EXPECTED_DATE_MAX,
            f"{dmin.date()} to {dmax.date()}",
            f"{EXPECTED_DATE_MIN} to {EXPECTED_DATE_MAX}",
        )
        _check(
            report["checks"],
            "orders_distinct_days",
            ndays == EXPECTED_DAYS,
            ndays,
            EXPECTED_DAYS,
        )
        if span is not None:
            passed = span - ndays == 0
            if not passed:
                ok = False
            _check(
                report["checks"],
                "orders_no_missing_days",
                passed,
                span - ndays,
                0,
                "missing calendar days in orders",
            )
        bad_dates = int(dates.isna().sum())
        _check(
            report["checks"],
            "orders_no_unparseable_dates",
            bad_dates == 0,
            bad_dates,
            0,
        )

    # --- Joins + revenue / payments ---------------------------------------
    if "orders" in tables and "order_items" in tables:
        print("\nJoin + revenue check:")
        orders, items = tables["orders"], tables["order_items"]
        if "order_id" in orders.columns and "order_id" in items.columns:
            unmatched_orders = int(
                (~items["order_id"].isin(set(orders["order_id"]))).sum()
            )
            _check(
                report["checks"],
                "order_items_unmatched_to_orders",
                unmatched_orders == 0,
                unmatched_orders,
                0,
            )
            if unmatched_orders:
                ok = False
        if (
            "product_id" in items.columns
            and "products" in tables
            and "product_id" in tables["products"].columns
        ):
            unmatched_prod = int(
                (~items["product_id"].isin(set(tables["products"]["product_id"]))).sum()
            )
            _check(
                report["checks"],
                "order_items_unmatched_to_products",
                unmatched_prod == 0,
                unmatched_prod,
                0,
            )
            if unmatched_prod:
                ok = False
        if {"qty", "price"}.issubset(items.columns):
            revenue = float((items["qty"] * items["price"]).sum())
            passed = abs(revenue - EXPECTED_REVENUE) < 1.0
            if not passed:
                ok = False
            _check(
                report["checks"],
                "revenue_qty_x_price",
                passed,
                round(revenue),
                EXPECTED_REVENUE,
                "qty*price only — never payments",
            )
            neg_qty = int((items["qty"] <= 0).sum()) if "qty" in items else 0
            neg_price = int((items["price"] < 0).sum())
            _check(
                report["checks"],
                "order_items_no_bad_qty_price",
                neg_qty == 0 and neg_price == 0,
                f"qty<=0:{neg_qty} price<0:{neg_price}",
                "qty<=0:0 price<0:0",
            )

    if "payments" in tables and "amount" in tables["payments"].columns:
        print("\nPayments check (reconciliation only):")
        total = float(tables["payments"]["amount"].sum())
        passed = abs(total - EXPECTED_PAYMENTS) < 1.0
        if not passed:
            ok = False
        _check(
            report["checks"],
            "payments_total",
            passed,
            round(total),
            EXPECTED_PAYMENTS,
            "DIFFERENT from revenue — do not mix them",
        )
        if "order_id" in tables["payments"].columns and "orders" in tables:
            unmatched_pay = int(
                (
                    ~tables["payments"]["order_id"].isin(
                        set(tables["orders"]["order_id"])
                    )
                ).sum()
            )
            _check(
                report["checks"],
                "payments_unmatched_to_orders",
                unmatched_pay == 0,
                unmatched_pay,
                0,
            )

    failed = [c for c in report["checks"] if c["status"] == "FAIL"]
    report["overall"] = "PASS" if not failed and ok else "FAIL"
    report["failed_count"] = len(failed)

    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    # Human-readable summary for the repo.
    lines = [
        "# Step 2 — Data profile\n",
        f"Generated: {report['generated_at']}  \n",
        f"Overall: **{report['overall']}** "
        f"({len(report['checks'])} checks, {len(failed)} failed)\n",
        "Source: Kaggle Retail Data Warehouse "
        "(datarspectrum), CSVs in `data/raw/` (not committed).\n",
        "## Files found\n",
    ]
    for name, s in report["files"].items():
        lines.append(
            f"- **{name}**: {s['rows']:,} rows, "
            f"{s['column_count']} columns "
            f"({', '.join(s['columns'])}), "
            f"{s['null_total']:,} nulls, "
            f"{s['duplicate_full_rows']:,} duplicate rows"
        )
    lines.append("\n## Checks\n")
    for c in report["checks"]:
        lines.append(
            f"- [{'PASS' if c['status'] == 'PASS' else 'FAIL'}] "
            f"**{c['check']}**: {c['actual']} "
            f"(expected {c['expected']})" + (f" — {c['note']}" if c["note"] else "")
        )
    lines.append("\n## Rules this profile enforces\n")
    lines.append(
        "- Revenue is always `qty * price` from order_items. "
        "Payments are a separate total, for reconciliation only."
    )
    lines.append(
        "- Any FAIL above must be investigated and recorded in "
        "docs/DESIGN.md before Step 3 loads the data — "
        "do not load around a failing check."
    )
    with open(MD_OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\nWrote {JSON_OUT}")
    print(f"Wrote {MD_OUT}")
    print(
        f"\nPROFILE {'PASS' if report['overall'] == 'PASS' else 'FAIL'} "
        f"— {len(failed)} check(s) failed"
    )
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
