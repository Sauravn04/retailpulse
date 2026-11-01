"""Step 3b — Build Silver + Gold from Bronze (PostgreSQL).

Run:  python scripts/load_silver_gold.py
Needs: Bronze complete first — `python scripts/load_bronze.py`
       must have said "Bronze load OK" (12/12 files). If Bronze is
       still partial (1 Nov 2026: the server crashed on shipments.csv,
       file 10 of 12), rerun load_bronze.py first; this script refuses
       to build Silver from an incomplete Bronze.

What it does
------------
* Reads the column names of every bronze.* table at runtime from
  information_schema — it does NOT assume the CSV headers.
  Why: docs/PROFILE.md was received 1 Nov 2026 with the exact
  headers for all 12 files (see below). The old v2 DDL does NOT
  match the real CSV column counts — e.g. products.csv has 4
  columns but the v2 schema lists 3, orders.csv has 5 but v2
  lists 4. So this script:
    - requires the join / measure columns that Step 2 actually
      proved (order_id, customer_id, store_id, product_id,
      category_id, qty, price, amount, order_date) — if one is
      missing it FAILS and prints the actual bronze columns, so
      Saurav can paste them back instead of uploading a file;
    - accepts common aliases for descriptive columns
      (category_name / category, city, signup_date);
    - reports any other bronze column (the extra products /
      orders columns) and prints it. Those columns stay in
      Bronze (nothing is lost there); Silver carries them only
      where they are unambiguous — orders extras as TEXT, and
      products.supplier_id as INT if that is the extra column.
      Any other extra is NOT typed in Silver until Saurav
      confirms what it is — the script prints it for that.
* Silver (schema `silver`, typed, PKs): all 12 tables —
  categories, stores, suppliers, promotions, customers,
  products, employees, orders, order_items, payments,
  returns, shipments. Exact columns from docs/PROFILE.md
  (1 Nov 2026): categories(category_id, category_name),
  customers(customer_id, city, signup_date),
  employees(employee_id, store_id, salary),
  order_items(order_item_id, order_id, product_id, qty, price),
  orders(order_id, customer_id, store_id, order_date, promotion_id),
  payments(payment_id, order_id, amount),
  products(product_id, category_id, supplier_id, price),
  promotions(promotion_id, discount),
  returns(return_id, order_item_id, refund),
  shipments(shipment_id, order_id, status),
  stores(store_id, city), suppliers(supplier_id, country).
  orders.promotion_id is typed INT (not TEXT); products.supplier_id
  is typed INT. FKs are checked by quarantine queries, not by
  hard REFERENCES, so one bad row cannot abort the whole load.
  Cleaning: deduplicate on PK (extras -> quarantine.bad_rows),
  null keys -> quarantine, qty <= 0 / price < 0 -> quarantine,
  unmatched FKs -> quarantine. Nothing is silently dropped.
  Expected on this dataset: 0 quarantined rows (Step 2 found
  0 nulls, 0 duplicates, 0 unmatched items) — if the count is
  not 0, that is a finding, printed, not hidden.
* Gold (schema `gold`, rebuilt from Silver only, never Bronze
  or CSVs): daily_sales (1,462 rows), daily_category_sales
  (43,860 rows), daily_store_sales, monthly_sales (49 months:
  Jan 2020 – Jan 2024). RFM is Step 4, not built here.
* Reconciliation gate, before Gold is claimed done:
  Silver revenue = Gold daily = Gold category = Gold store
  = SUM(qty * price) = 3,827,746,136, and payments total
  = 3,018,080,810 (separate total, never mixed into revenue).
  If any mart disagrees, the script exits 1 and says which one.
* Logs one row per table in ops.pipeline_runs (stage silver/gold).
* Creates ops.pipeline_runs + quarantine.bad_rows itself at
  the start (sql/01_schema.sql) — never assumes they exist.
* Indexes are created AFTER the load, not before.

Needs: DATABASE_URL in .env, Postgres running, retailpulse DB.
Exit 0 only if Silver + Gold both reconcile. Exit 1 otherwise.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

EXPECTED_REVENUE = 3_827_746_136
EXPECTED_PAYMENTS = 3_018_080_810
EXPECTED_COUNTS = {
    "categories": 30, "stores": 100, "products": 10_000,
    "customers": 50_000, "orders": 300_000,
    "order_items": 600_000, "payments": 300_000,
    "employees": 1_000, "promotions": 50, "returns": 30_000,
    "shipments": 300_000, "suppliers": 200,
}
# Join / measure columns Step 2 proved (profiler used these names
# and its checks passed on the real data, 1 Nov 2026).
REQUIRED = {
    "categories": ["category_id"],
    "stores": ["store_id"],
    "customers": ["customer_id"],
    "products": ["product_id", "category_id", "price"],
    "orders": ["order_id", "customer_id", "store_id", "order_date",
             "promotion_id"],
    "order_items": ["order_item_id", "order_id", "product_id", "qty", "price"],
    "payments": ["payment_id", "order_id", "amount"],
}
# Descriptive columns: expected name -> acceptable aliases in Bronze.
ALIASES = {
    "category_name": ["category_name", "category", "name"],
    "city": ["city", "store_city", "customer_city"],
    "signup_date": ["signup_date", "sign_up_date", "created_date"],
    "payment_date": ["payment_date", "date"],
    "supplier_id": ["supplier_id"],
}
IGNORED_BRONZE_COLS = {"_source_file", "_loaded_at"}


def _quote(name):
    if not name.replace("_", "").isalnum():
        raise ValueError(f"Unsafe identifier: {name!r}")
    return f'"{name}"'


def _connect(url):
    import psycopg2
    return psycopg2.connect(url)


def _bronze_columns(cur, table):
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='bronze' AND table_name=%s "
        "ORDER BY ordinal_position",
        (table,),
    )
    return [r[0] for r in cur.fetchall()]


def _pick(actual, expected, table):
    """Return the bronze column to use for `expected`, or None.

    Exact match first, then a known alias, then — only for a
    descriptive column on a table where exactly one non-key
    column is left over — that column, renamed in Silver.
    Returns None if nothing fits; the caller decides if it is
    required (fail) or optional (omit).
    """
    if expected in actual:
        return expected
    for alias in ALIASES.get(expected, []):
        if alias in actual:
            print(f"  NOTE {table}: using bronze column {alias!r} as {expected}")
            return alias
    return None


def _quarantine(cur, stage, source_file, pk, reason, raw_sql):
    cur.execute(
        "INSERT INTO quarantine.bad_rows "
        "(stage, source_file, source_pk, reason, raw_row) "
        f"SELECT %s, %s, %s, %s, {raw_sql}",
        (stage, source_file, pk, reason),
    )


def main() -> int:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("[FAIL] DATABASE_URL not set — copy .env.example to .env")
        return 1
    conn = _connect(url)
    try:
        # Create schemas + ops.pipeline_runs + quarantine.bad_rows
        # if missing (sql/01_schema.sql, IF NOT EXISTS). This script
        # used to assume they already existed — 1 Nov 2026 it failed
        # at the first log() with: relation "ops.pipeline_runs"
        # does not exist. Never assume; create them here.
        with conn.cursor() as cur:
            with open(os.path.join(ROOT, "sql", "01_schema.sql")) as f:
                cur.execute(f.read())
        conn.commit()
    except Exception as exc:
        print(f"[FAIL] Could not create schemas / ops.pipeline_runs: {exc}")
        print("Run once in psql, as retailpulse_user in the retailpulse DB:")
        print(r"  \i sql/01_schema.sql")
        print("then rerun: python scripts/load_silver_gold.py")
        return 1
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # --- 0. Bronze must be complete -------------------------------
            print("Checking Bronze is complete (12/12 files) ...")
            for table, expected in EXPECTED_COUNTS.items():
                cur.execute(f"SELECT count(*) FROM bronze.{_quote(table)}")
                n = cur.fetchone()[0]
                mark = "ok" if n == expected else "MISMATCH"
                print(f"  bronze.{table}: {n:,} rows (expected {expected:,}) [{mark}]")
                if n != expected:
                    print(f"[FAIL] Bronze incomplete for {table}. "
                          "Rerun: python scripts/load_bronze.py")
                    return 1

            # --- 1. Discover bronze columns -------------------------------
            print("\nBronze columns (read from Postgres, not assumed):")
            cols = {}
            for table in REQUIRED:
                actual = _bronze_columns(cur, table)
                cols[table] = actual
                print(f"  bronze.{table}: {actual}")
                missing = [c for c in REQUIRED[table] if c not in actual]
                if missing:
                    print(f"[FAIL] bronze.{table} is missing required "
                          f"column(s): {missing}")
                    print("Paste the bronze column list above back to Muse "
                          "— do not edit this script to guess the names.")
                    return 1

            # Descriptive columns, with alias fallback.
            desc = {}
            for table, names in {
                "categories": ["category_name"],
                "stores": ["city"],
                "customers": ["city", "signup_date"],
                "payments": ["payment_date"],
            }.items():
                for name in names:
                    got = _pick(cols[table], name, table)
                    desc[(table, name)] = got
                    if got is None and name != "payment_date":
                        print(f"[FAIL] bronze.{table}: no column found for "
                              f"{name} (tried {ALIASES.get(name)})")
                        return 1
            # products: optional supplier_id, carried as INT if present.
            prod_supplier = _pick(cols["products"], "supplier_id", "products")

            # Extra columns carried to Silver as TEXT (nothing dropped).
            def extras(table, used):
                return [c for c in cols[table]
                        if c not in used and c not in IGNORED_BRONZE_COLS]

            used = {
                "categories": set(REQUIRED["categories"]) | {desc[("categories", "category_name")]},
                "stores": set(REQUIRED["stores"]) | {desc[("stores", "city")]},
                "customers": set(REQUIRED["customers"]) | {
                    desc[("customers", "city")], desc[("customers", "signup_date")]},
                "products": set(REQUIRED["products"]) | (
                    {prod_supplier} if prod_supplier else set()),
                "orders": set(REQUIRED["orders"]),
                "order_items": set(REQUIRED["order_items"]),
                "payments": set(REQUIRED["payments"]) | (
                    {desc[("payments", "payment_date")]}
                    if desc[("payments", "payment_date")] else set()),
            }
            extra_cols = {t: extras(t, used[t]) for t in REQUIRED}
            for t, ex in extra_cols.items():
                if ex:
                    print(f"  NOTE silver.{t}: extra bronze column(s) {ex} "
                          "carried as TEXT — confirm what they mean, "
                          "then type them properly in a later step.")

            def log(stage, table, rows, quarantined=0, status="ok", note=""):
                cur.execute(
                    "INSERT INTO ops.pipeline_runs (stage, source_file, "
                    "table_name, rows_loaded, rows_quarantined, status, note) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (stage, f"bronze.{table}", f"{stage}.{table}",
                     rows, quarantined, status, note or None),
                )

            def count_quarantined(source):
                cur.execute(
                    "SELECT count(*) FROM quarantine.bad_rows "
                    "WHERE stage='silver' AND source_file=%s", (source,))
                return cur.fetchone()[0]

            # --- 2. Silver ------------------------------------------------
            print("\nBuilding Silver ...")
            cat = desc[("categories", "category_name")]
            store_city = desc[("stores", "city")]
            cust_city = desc[("customers", "city")]
            cust_signup = desc[("customers", "signup_date")]
            pay_date = desc[("payments", "payment_date")]

            # Helper: build a Silver table from Bronze with dedup +
            # quarantine, for the simple dimension tables.
            def build_dim(table, pk, select_sql, extra_text_cols):
                # Quarantine duplicates on PK (keep first).
                cur.execute(
                    f"INSERT INTO quarantine.bad_rows "
                    f"(stage, source_file, source_pk, reason, raw_row) "
                    f"SELECT 'silver', 'bronze.{table}', "
                    f"({pk})::text, 'duplicate ' || %s, "
                    f"row_to_json(b)::text FROM ("
                    f"SELECT *, ROW_NUMBER() OVER (PARTITION BY {pk} "
                    f"ORDER BY {pk}) AS _rn FROM bronze.{table}) b "
                    f"WHERE _rn > 1",
                    (pk,),
                )
                # Quarantine null PKs.
                cur.execute(
                    f"INSERT INTO quarantine.bad_rows "
                    f"(stage, source_file, source_pk, reason, raw_row) "
                    f"SELECT 'silver', 'bronze.{table}', NULL, "
                    f"'null ' || %s, row_to_json(b)::text "
                    f"FROM bronze.{table} b WHERE {pk} IS NULL OR "
                    f"TRIM({pk}) = ''",
                    (pk,),
                )
                cur.execute(f"DROP TABLE IF EXISTS silver.{table}")
                cur.execute(
                    f"CREATE TABLE silver.{table} AS {select_sql}")
                # CREATE TABLE AS keeps no PK — add it now (the
                # DISTINCT ON above guarantees uniqueness).
                cur.execute(
                    f"ALTER TABLE silver.{table} "
                    f"ADD PRIMARY KEY ({_quote(pk)})")
                cur.execute(f"SELECT count(*) FROM silver.{table}")
                n = cur.fetchone()[0]
                q = count_quarantined(f"bronze.{table}")
                log("silver", table, n, q)
                print(f"  silver.{table}: {n:,} rows, {q:,} quarantined")
                return n

            # categories
            build_dim(
                "categories", "category_id",
                f"SELECT DISTINCT ON (category_id::int) "
                f"category_id::int AS category_id, "
                f"{_quote(cat)} AS category_name "
                f"FROM bronze.categories "
                f"WHERE category_id IS NOT NULL AND TRIM(category_id) <> '' "
                f"ORDER BY category_id::int",
                extra_cols["categories"],
            )
            # stores
            build_dim(
                "stores", "store_id",
                f"SELECT DISTINCT ON (store_id::int) "
                f"store_id::int AS store_id, "
                f"{_quote(store_city)} AS city "
                f"FROM bronze.stores "
                f"WHERE store_id IS NOT NULL AND TRIM(store_id) <> '' "
                f"ORDER BY store_id::int",
                extra_cols["stores"],
            )
            # customers
            build_dim(
                "customers", "customer_id",
                f"SELECT DISTINCT ON (customer_id::int) "
                f"customer_id::int AS customer_id, "
                f"{_quote(cust_city)} AS city, "
                f"{_quote(cust_signup)}::date AS signup_date "
                f"FROM bronze.customers "
                f"WHERE customer_id IS NOT NULL AND TRIM(customer_id) <> '' "
                f"ORDER BY customer_id::int",
                extra_cols["customers"],
            )
            # suppliers + promotions (dims, no FKs) — needed so
            # products.supplier_id and orders.promotion_id can be checked.
            build_dim(
                "suppliers", "supplier_id",
                "SELECT DISTINCT ON (supplier_id::int) "
                "supplier_id::int AS supplier_id, country AS country "
                "FROM bronze.suppliers "
                "WHERE supplier_id IS NOT NULL AND TRIM(supplier_id) <> '' "
                "ORDER BY supplier_id::int",
                extra_cols.get("suppliers", []),
            )
            build_dim(
                "promotions", "promotion_id",
                "SELECT DISTINCT ON (promotion_id::int) "
                "promotion_id::int AS promotion_id, "
                "discount::numeric AS discount "
                "FROM bronze.promotions "
                "WHERE promotion_id IS NOT NULL AND TRIM(promotion_id) <> '' "
                "ORDER BY promotion_id::int",
                extra_cols.get("promotions", []),
            )
            # products (optional supplier_id carried as INT; any
            # other extra bronze column carried as TEXT, like orders)
            sup_select = (
                f", p.{_quote(prod_supplier)}::int AS supplier_id"
                if prod_supplier else ""
            )
            sup_col = ", supplier_id INT" if prod_supplier else ""
            prod_extra = [c for c in extra_cols["products"]
                          if c != prod_supplier]
            prod_extra_def = "".join(
                f", {_quote(c)} TEXT" for c in prod_extra)
            prod_extra_sel = "".join(
                f", p.{_quote(c)}" for c in prod_extra)
            cur.execute("DROP TABLE IF EXISTS silver.products")
            cur.execute(
                f"CREATE TABLE silver.products ("
                f"product_id INT PRIMARY KEY, category_id INT NOT NULL, "
                f"price NUMERIC(12,2) NOT NULL CHECK (price >= 0)"
                f"{sup_col}{prod_extra_def})"
            )
            # duplicates / nulls / bad price -> quarantine, then load clean
            cur.execute(
                "INSERT INTO quarantine.bad_rows "
                "(stage, source_file, source_pk, reason, raw_row) "
                "SELECT 'silver', 'bronze.products', product_id::text, "
                "'duplicate product_id', row_to_json(b)::text FROM ("
                "SELECT *, ROW_NUMBER() OVER (PARTITION BY product_id "
                "ORDER BY product_id) AS _rn FROM bronze.products) b "
                "WHERE _rn > 1"
            )
            cur.execute(
                "INSERT INTO quarantine.bad_rows "
                "(stage, source_file, source_pk, reason, raw_row) "
                "SELECT 'silver', 'bronze.products', b.product_id::text, "
                "'bad price, null key or unmatched category_id', "
                "row_to_json(b)::text "
                "FROM bronze.products b "
                "LEFT JOIN silver.categories c "
                "  ON c.category_id = b.category_id::int "
                "WHERE b.product_id IS NULL OR TRIM(b.product_id) = '' "
                "OR b.price IS NULL OR b.price::numeric < 0 "
                "OR c.category_id IS NULL"
            )
            cur.execute(
                "INSERT INTO silver.products "
                "SELECT DISTINCT ON (p.product_id::int) "
                "p.product_id::int, p.category_id::int, "
                "p.price::numeric(12,2)"
                f"{sup_select}{prod_extra_sel} "
                "FROM bronze.products p "
                "JOIN silver.categories c "
                "  ON c.category_id = p.category_id::int "
                "WHERE p.product_id IS NOT NULL "
                "AND TRIM(p.product_id) <> '' "
                "AND p.price IS NOT NULL AND p.price::numeric >= 0 "
                "ORDER BY p.product_id::int"
            )
            cur.execute("SELECT count(*) FROM silver.products")
            n = cur.fetchone()[0]
            q = count_quarantined("bronze.products")
            log("silver", "products", n, q)
            print(f"  silver.products: {n:,} rows, {q:,} quarantined")

            # employees (FK store_id checked by quarantine).
            cur.execute("DROP TABLE IF EXISTS silver.employees")
            cur.execute(
                "CREATE TABLE silver.employees ("
                "employee_id INT PRIMARY KEY, store_id INT NOT NULL, "
                "salary NUMERIC(12,2) NOT NULL)"
            )
            cur.execute(
                "INSERT INTO quarantine.bad_rows "
                "(stage, source_file, source_pk, reason, raw_row) "
                "SELECT 'silver', 'bronze.employees', employee_id::text, "
                "'unmatched store_id', row_to_json(e)::text "
                "FROM bronze.employees e "
                "LEFT JOIN silver.stores s ON s.store_id = e.store_id::int "
                "WHERE s.store_id IS NULL"
            )
            cur.execute(
                "INSERT INTO silver.employees "
                "SELECT DISTINCT ON (e.employee_id::int) "
                "e.employee_id::int, e.store_id::int, e.salary::numeric(12,2) "
                "FROM bronze.employees e "
                "JOIN silver.stores s ON s.store_id = e.store_id::int "
                "ORDER BY e.employee_id::int"
            )
            cur.execute("SELECT count(*) FROM silver.employees")
            n = cur.fetchone()[0]
            q = count_quarantined("bronze.employees")
            log("silver", "employees", n, q)
            print(f"  silver.employees: {n:,} rows, {q:,} quarantined")

            # orders — promotion_id is INT (PROFILE.md, 1 Nov 2026),
            # not a TEXT extra. Unmatched promotion_ids are counted
            # and printed below, not quarantined, because 0 may mean
            # "no promotion" — that is a finding, not a load failure.
            ord_extra = [c for c in extra_cols["orders"]
                         if c != "promotion_id"]
            ord_extra_def = "".join(
                f", {_quote(c)} TEXT" for c in ord_extra)
            ord_extra_sel = "".join(
                f", o.{_quote(c)}" for c in ord_extra)
            cur.execute("DROP TABLE IF EXISTS silver.orders")
            cur.execute(
                f"CREATE TABLE silver.orders ("
                f"order_id INT PRIMARY KEY, customer_id INT, "
                f"store_id INT NOT NULL, order_date DATE NOT NULL, "
                f"promotion_id INT"
                f"{ord_extra_def})"
            )
            cur.execute(
                "INSERT INTO quarantine.bad_rows "
                "(stage, source_file, source_pk, reason, raw_row) "
                "SELECT 'silver', 'bronze.orders', order_id::text, "
                "'duplicate order_id', row_to_json(b)::text FROM ("
                "SELECT *, ROW_NUMBER() OVER (PARTITION BY order_id "
                "ORDER BY order_id) AS _rn FROM bronze.orders) b "
                "WHERE _rn > 1"
            )
            cur.execute(
                "INSERT INTO quarantine.bad_rows "
                "(stage, source_file, source_pk, reason, raw_row) "
                "SELECT 'silver', 'bronze.orders', o.order_id::text, "
                "'unmatched customer_id or store_id', "
                "row_to_json(o)::text FROM bronze.orders o "
                "LEFT JOIN silver.customers c "
                "  ON c.customer_id = o.customer_id::int "
                "LEFT JOIN silver.stores s "
                "  ON s.store_id = o.store_id::int "
                "WHERE (o.customer_id IS NOT NULL AND c.customer_id IS NULL) "
                "OR s.store_id IS NULL"
            )
            cur.execute(
                "INSERT INTO silver.orders "
                "SELECT DISTINCT ON (o.order_id::int) "
                "o.order_id::int, o.customer_id::int, o.store_id::int, "
                "o.order_date::date, o.promotion_id::int"
                f"{ord_extra_sel} "
                "FROM bronze.orders o "
                "JOIN silver.stores s ON s.store_id = o.store_id::int "
                "LEFT JOIN silver.customers c "
                "  ON c.customer_id = o.customer_id::int "
                "WHERE o.order_id IS NOT NULL AND TRIM(o.order_id) <> '' "
                "AND o.order_date IS NOT NULL "
                "AND (o.customer_id IS NULL OR c.customer_id IS NOT NULL) "
                "ORDER BY o.order_id::int"
            )
            cur.execute("SELECT count(*) FROM silver.orders")
            n = cur.fetchone()[0]
            q = count_quarantined("bronze.orders")
            log("silver", "orders", n, q)
            print(f"  silver.orders: {n:,} rows, {q:,} quarantined")

            # order_items — quarantine bad qty/price, unmatched FKs.
            cur.execute("DROP TABLE IF EXISTS silver.order_items")
            cur.execute(
                "CREATE TABLE silver.order_items ("
                "order_item_id INT PRIMARY KEY, order_id INT NOT NULL, "
                "product_id INT NOT NULL, qty INT NOT NULL CHECK (qty > 0), "
                "price NUMERIC(12,2) NOT NULL CHECK (price >= 0))"
            )
            cur.execute(
                "INSERT INTO quarantine.bad_rows "
                "(stage, source_file, source_pk, reason, raw_row) "
                "SELECT 'silver', 'bronze.order_items', "
                "order_item_id::text, 'duplicate order_item_id', "
                "row_to_json(b)::text FROM ("
                "SELECT *, ROW_NUMBER() OVER (PARTITION BY order_item_id "
                "ORDER BY order_item_id) AS _rn FROM bronze.order_items) b "
                "WHERE _rn > 1"
            )
            cur.execute(
                "INSERT INTO quarantine.bad_rows "
                "(stage, source_file, source_pk, reason, raw_row) "
                "SELECT 'silver', 'bronze.order_items', "
                "oi.order_item_id::text, "
                "'bad qty/price or unmatched order/product', "
                "row_to_json(oi)::text FROM bronze.order_items oi "
                "LEFT JOIN silver.orders o "
                "  ON o.order_id = oi.order_id::int "
                "LEFT JOIN silver.products p "
                "  ON p.product_id = oi.product_id::int "
                "WHERE oi.qty IS NULL OR oi.qty::int <= 0 "
                "OR oi.price IS NULL OR oi.price::numeric < 0 "
                "OR o.order_id IS NULL OR p.product_id IS NULL"
            )
            cur.execute(
                "INSERT INTO silver.order_items "
                "SELECT DISTINCT ON (oi.order_item_id::int) "
                "oi.order_item_id::int, oi.order_id::int, "
                "oi.product_id::int, oi.qty::int, oi.price::numeric(12,2) "
                "FROM bronze.order_items oi "
                "JOIN silver.orders o ON o.order_id = oi.order_id::int "
                "JOIN silver.products p ON p.product_id = oi.product_id::int "
                "WHERE oi.qty::int > 0 AND oi.price::numeric >= 0 "
                "ORDER BY oi.order_item_id::int"
            )
            cur.execute("SELECT count(*) FROM silver.order_items")
            n = cur.fetchone()[0]
            q = count_quarantined("bronze.order_items")
            log("silver", "order_items", n, q)
            print(f"  silver.order_items: {n:,} rows, {q:,} quarantined")

            # payments — reconciliation only, never joined into revenue.
            pay_date_sel = (
                f", p.{_quote(pay_date)}::date AS payment_date"
                if pay_date else ""
            )
            pay_date_def = ", payment_date DATE" if pay_date else ""
            cur.execute("DROP TABLE IF EXISTS silver.payments")
            cur.execute(
                f"CREATE TABLE silver.payments ("
                f"payment_id INT PRIMARY KEY, order_id INT NOT NULL, "
                f"amount NUMERIC(14,2) NOT NULL{pay_date_def})"
            )
            # Duplicates first, then unmatched order_ids — as two
            # separate inserts, so the join is not lost in a subquery.
            cur.execute(
                "INSERT INTO quarantine.bad_rows "
                "(stage, source_file, source_pk, reason, raw_row) "
                "SELECT 'silver', 'bronze.payments', payment_id::text, "
                "'duplicate payment_id', row_to_json(b)::text FROM ("
                "SELECT *, ROW_NUMBER() OVER (PARTITION BY payment_id "
                "ORDER BY payment_id) AS _rn FROM bronze.payments) b "
                "WHERE _rn > 1"
            )
            cur.execute(
                "INSERT INTO quarantine.bad_rows "
                "(stage, source_file, source_pk, reason, raw_row) "
                "SELECT 'silver', 'bronze.payments', p.payment_id::text, "
                "'unmatched order_id', row_to_json(p)::text "
                "FROM bronze.payments p "
                "LEFT JOIN silver.orders o "
                "  ON o.order_id = p.order_id::int "
                "WHERE o.order_id IS NULL"
            )
            cur.execute(
                "INSERT INTO silver.payments "
                "SELECT DISTINCT ON (p.payment_id::int) "
                "p.payment_id::int, p.order_id::int, "
                "p.amount::numeric(14,2)"
                f"{pay_date_sel} "
                "FROM bronze.payments p "
                "JOIN silver.orders o ON o.order_id = p.order_id::int "
                "ORDER BY p.payment_id::int"
            )
            cur.execute("SELECT count(*) FROM silver.payments")
            n = cur.fetchone()[0]
            q = count_quarantined("bronze.payments")
            log("silver", "payments", n, q)
            print(f"  silver.payments: {n:,} rows, {q:,} quarantined")

            # returns + shipments (FKs checked by quarantine).
            cur.execute("DROP TABLE IF EXISTS silver.returns")
            cur.execute(
                "CREATE TABLE silver.returns ("
                "return_id INT PRIMARY KEY, order_item_id INT NOT NULL, "
                "refund NUMERIC(12,2) NOT NULL)"
            )
            cur.execute(
                "INSERT INTO quarantine.bad_rows "
                "(stage, source_file, source_pk, reason, raw_row) "
                "SELECT 'silver', 'bronze.returns', return_id::text, "
                "'unmatched order_item_id', row_to_json(r)::text "
                "FROM bronze.returns r "
                "LEFT JOIN silver.order_items oi "
                "  ON oi.order_item_id = r.order_item_id::int "
                "WHERE oi.order_item_id IS NULL"
            )
            cur.execute(
                "INSERT INTO silver.returns "
                "SELECT DISTINCT ON (r.return_id::int) "
                "r.return_id::int, r.order_item_id::int, "
                "r.refund::numeric(12,2) "
                "FROM bronze.returns r "
                "JOIN silver.order_items oi "
                "  ON oi.order_item_id = r.order_item_id::int "
                "ORDER BY r.return_id::int"
            )
            cur.execute("SELECT count(*) FROM silver.returns")
            n = cur.fetchone()[0]
            q = count_quarantined("bronze.returns")
            log("silver", "returns", n, q)
            print(f"  silver.returns: {n:,} rows, {q:,} quarantined")

            cur.execute("DROP TABLE IF EXISTS silver.shipments")
            cur.execute(
                "CREATE TABLE silver.shipments ("
                "shipment_id INT PRIMARY KEY, order_id INT NOT NULL, "
                "status TEXT NOT NULL)"
            )
            cur.execute(
                "INSERT INTO quarantine.bad_rows "
                "(stage, source_file, source_pk, reason, raw_row) "
                "SELECT 'silver', 'bronze.shipments', shipment_id::text, "
                "'unmatched order_id', row_to_json(s)::text "
                "FROM bronze.shipments s "
                "LEFT JOIN silver.orders o "
                "  ON o.order_id = s.order_id::int "
                "WHERE o.order_id IS NULL"
            )
            cur.execute(
                "INSERT INTO silver.shipments "
                "SELECT DISTINCT ON (s.shipment_id::int) "
                "s.shipment_id::int, s.order_id::int, s.status "
                "FROM bronze.shipments s "
                "JOIN silver.orders o ON o.order_id = s.order_id::int "
                "ORDER BY s.shipment_id::int"
            )
            cur.execute("SELECT count(*) FROM silver.shipments")
            n = cur.fetchone()[0]
            q = count_quarantined("bronze.shipments")
            log("silver", "shipments", n, q)
            print(f"  silver.shipments: {n:,} rows, {q:,} quarantined")

            # Unmatched promotion_id / supplier_id: count and report,
            # do not quarantine (0 may mean "no promotion").
            cur.execute(
                "SELECT count(*) FROM silver.orders o "
                "LEFT JOIN silver.promotions p "
                "  ON p.promotion_id = o.promotion_id "
                "WHERE o.promotion_id IS NOT NULL AND p.promotion_id IS NULL")
            print(f"  orders with unmatched promotion_id: "
                  f"{cur.fetchone()[0]:,} (reported, not quarantined)")
            cur.execute(
                "SELECT count(*) FROM silver.products p "
                "LEFT JOIN silver.suppliers s "
                "  ON s.supplier_id = p.supplier_id "
                "WHERE p.supplier_id IS NOT NULL AND s.supplier_id IS NULL")
            print(f"  products with unmatched supplier_id: "
                  f"{cur.fetchone()[0]:,} (reported, not quarantined)")

            # Silver revenue + payments totals (the gate, part 1).
            cur.execute(
                "SELECT COALESCE(SUM(qty * price), 0) "
                "FROM silver.order_items")
            silver_revenue = cur.fetchone()[0]
            cur.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM silver.payments")
            payments_total = cur.fetchone()[0]
            print(f"\nSilver revenue (qty*price): {silver_revenue:,} "
                  f"(expected {EXPECTED_REVENUE:,})")
            print(f"Silver payments total: {payments_total:,} "
                  f"(expected {EXPECTED_PAYMENTS:,})")
            if silver_revenue != EXPECTED_REVENUE:
                print("[FAIL] Silver revenue does not reconcile — "
                      "Gold will NOT be built. Fix Silver first.")
                conn.rollback()
                return 1
            if payments_total != EXPECTED_PAYMENTS:
                print("[FAIL] Payments total does not reconcile — "
                      "check silver.payments before building Gold.")
                conn.rollback()
                return 1

            # --- 3. Gold (from Silver only) -------------------------------
            print("\nBuilding Gold from Silver only ...")
            cur.execute("DROP TABLE IF EXISTS gold.daily_sales")
            cur.execute(
                "CREATE TABLE gold.daily_sales AS "
                "SELECT o.order_date, "
                "SUM(oi.qty * oi.price) AS revenue, "
                "SUM(oi.qty) AS quantity, "
                "COUNT(DISTINCT o.order_id) AS orders "
                "FROM silver.orders o "
                "JOIN silver.order_items oi ON oi.order_id = o.order_id "
                "GROUP BY o.order_date ORDER BY o.order_date"
            )
            cur.execute(
                "ALTER TABLE gold.daily_sales "
                "ADD PRIMARY KEY (order_date)")
            cur.execute("DROP TABLE IF EXISTS gold.daily_category_sales")
            cur.execute(
                "CREATE TABLE gold.daily_category_sales AS "
                "SELECT o.order_date, p.category_id, "
                "SUM(oi.qty * oi.price) AS revenue, "
                "SUM(oi.qty) AS quantity "
                "FROM silver.orders o "
                "JOIN silver.order_items oi ON oi.order_id = o.order_id "
                "JOIN silver.products p ON p.product_id = oi.product_id "
                "GROUP BY o.order_date, p.category_id"
            )
            cur.execute(
                "ALTER TABLE gold.daily_category_sales "
                "ADD PRIMARY KEY (order_date, category_id)")
            cur.execute("DROP TABLE IF EXISTS gold.daily_store_sales")
            cur.execute(
                "CREATE TABLE gold.daily_store_sales AS "
                "SELECT o.order_date, o.store_id, "
                "SUM(oi.qty * oi.price) AS revenue, "
                "SUM(oi.qty) AS quantity "
                "FROM silver.orders o "
                "JOIN silver.order_items oi ON oi.order_id = o.order_id "
                "GROUP BY o.order_date, o.store_id"
            )
            cur.execute(
                "ALTER TABLE gold.daily_store_sales "
                "ADD PRIMARY KEY (order_date, store_id)")
            cur.execute("DROP TABLE IF EXISTS gold.monthly_sales")
            cur.execute(
                "CREATE TABLE gold.monthly_sales AS "
                "SELECT DATE_TRUNC('month', order_date)::date AS month, "
                "SUM(revenue) AS revenue, SUM(quantity) AS quantity, "
                "SUM(orders) AS orders "
                "FROM gold.daily_sales GROUP BY 1 ORDER BY 1"
            )
            cur.execute(
                "ALTER TABLE gold.monthly_sales ADD PRIMARY KEY (month)")

            for table in ("daily_sales", "daily_category_sales",
                          "daily_store_sales", "monthly_sales"):
                cur.execute(f"SELECT count(*) FROM gold.{table}")
                n = cur.fetchone()[0]
                log("gold", table, n)
                print(f"  gold.{table}: {n:,} rows")

            # Indexes after the load.
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_silver_orders_date "
                "ON silver.orders (order_date)")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_silver_items_order "
                "ON silver.order_items (order_id)")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_silver_items_product "
                "ON silver.order_items (product_id)")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_gold_daily_cat "
                "ON gold.daily_category_sales (category_id, order_date)")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_gold_daily_store "
                "ON gold.daily_store_sales (store_id, order_date)")

            # --- 4. Reconciliation gate (Gold) ----------------------------
            print("\nReconciliation gate:")
            totals = {}
            for table in ("daily_sales", "daily_category_sales",
                          "daily_store_sales", "monthly_sales"):
                cur.execute(f"SELECT SUM(revenue) FROM gold.{table}")
                totals[table] = cur.fetchone()[0]
                mark = "ok" if totals[table] == EXPECTED_REVENUE else "FAIL"
                print(f"  gold.{table} revenue: {totals[table]:,} [{mark}]")
            cur.execute("SELECT count(*) FROM quarantine.bad_rows "
                        "WHERE stage='silver'")
            total_q = cur.fetchone()[0]
            print(f"  Total quarantined in Silver: {total_q:,} "
                  "(expected 0 on this dataset)")
            ok = all(v == EXPECTED_REVENUE for v in totals.values())
            if not ok:
                print("[FAIL] Gold totals do not reconcile to "
                      f"{EXPECTED_REVENUE:,}. Do not use Gold yet.")
                conn.rollback()
                return 1
            conn.commit()
            print("\nSilver + Gold OK — revenue reconciles to "
                  f"{EXPECTED_REVENUE:,} in every mart.")
            print("Next: Step 4 SQL analytics (window functions, RFM).")
            print("If any extra bronze column was noted above, paste "
                  "that line back so it can be typed properly.")
            return 0
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[FAIL] Silver/Gold build failed: {exc}")
        return 1
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
