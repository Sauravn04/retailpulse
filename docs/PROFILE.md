# Step 2 — Data profile

Generated: 2026-11-01T11:59:17  

Overall: **PASS** (16 checks, 0 failed)

Source: Kaggle Retail Data Warehouse (datarspectrum), CSVs in `data/raw/` (not committed).

## Files found

- **categories**: 30 rows, 2 columns (category_id, category_name), 0 nulls, 0 duplicate rows
- **customers**: 50,000 rows, 3 columns (customer_id, city, signup_date), 0 nulls, 0 duplicate rows
- **employees**: 1,000 rows, 3 columns (employee_id, store_id, salary), 0 nulls, 0 duplicate rows
- **order_items**: 600,000 rows, 5 columns (order_item_id, order_id, product_id, qty, price), 0 nulls, 0 duplicate rows
- **orders**: 300,000 rows, 5 columns (order_id, customer_id, store_id, order_date, promotion_id), 0 nulls, 0 duplicate rows
- **payments**: 300,000 rows, 3 columns (payment_id, order_id, amount), 0 nulls, 0 duplicate rows
- **products**: 10,000 rows, 4 columns (product_id, category_id, supplier_id, price), 0 nulls, 0 duplicate rows
- **promotions**: 50 rows, 2 columns (promotion_id, discount), 0 nulls, 0 duplicate rows
- **returns**: 30,000 rows, 3 columns (return_id, order_item_id, refund), 0 nulls, 0 duplicate rows
- **shipments**: 300,000 rows, 3 columns (shipment_id, order_id, status), 0 nulls, 0 duplicate rows
- **stores**: 100 rows, 2 columns (store_id, city), 0 nulls, 0 duplicate rows
- **suppliers**: 200 rows, 2 columns (supplier_id, country), 0 nulls, 0 duplicate rows

## Checks

- [PASS] **core_files_present**: 7/7 present (expected all 7 core files)
- [PASS] **rows_categories**: 30 (expected 30)
- [PASS] **rows_stores**: 100 (expected 100)
- [PASS] **rows_products**: 10000 (expected 10000)
- [PASS] **rows_orders**: 300000 (expected 300000)
- [PASS] **rows_order_items**: 600000 (expected 600000)
- [PASS] **orders_date_range**: 2020-01-01 to 2024-01-01 (expected 2020-01-01 to 2024-01-01)
- [PASS] **orders_distinct_days**: 1462 (expected 1462)
- [PASS] **orders_no_missing_days**: 0 (expected 0) — missing calendar days in orders
- [PASS] **orders_no_unparseable_dates**: 0 (expected 0)
- [PASS] **order_items_unmatched_to_orders**: 0 (expected 0)
- [PASS] **order_items_unmatched_to_products**: 0 (expected 0)
- [PASS] **revenue_qty_x_price**: 3827746136 (expected 3827746136) — qty*price only — never payments
- [PASS] **order_items_no_bad_qty_price**: qty<=0:0 price<0:0 (expected qty<=0:0 price<0:0)
- [PASS] **payments_total**: 3018080810 (expected 3018080810) — DIFFERENT from revenue — do not mix them
- [PASS] **payments_unmatched_to_orders**: 0 (expected 0)

## Rules this profile enforces

- Revenue is always `qty * price` from order_items. Payments are a separate total, for reconciliation only.
- Any FAIL above must be investigated and recorded in docs/DESIGN.md before Step 3 loads the data — do not load around a failing check.
