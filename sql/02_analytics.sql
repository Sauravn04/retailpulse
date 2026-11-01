-- RetailPulse Step 4 — SQL analytics (window functions + RFM)
-- Run:  python scripts/run_analytics.py
--       (or: psql -U retailpulse_user -d retailpulse -h 127.0.0.1 -f sql/02_analytics.sql)
-- Reads Gold only, never Bronze or CSVs. All objects are in gold.*.
-- Idempotent: views are CREATE OR REPLACE, rfm_customers is
-- DROP + CREATE, so a rerun rebuilds everything from current Gold.
--
-- Business questions answered (see docs/DESIGN.md):
--   1. Which categories / stores drive revenue?  -> v_top_categories, v_top_stores
--   2. Is revenue growing week-over-week / month-over-month? -> v_daily_trend, v_monthly_trend
--   3. Which customers are recent, frequent, high-value? -> rfm_customers
--   5. Where is the data not trustworthy? -> scripts/run_analytics.py checks

-- 1. Daily trend: 7d / 30d rolling revenue, yesterday vs 7 days ago,
--    cumulative revenue. First 6 days have a partial 7d window —
--    that is honest, not hidden: rolling_7d_revenue is the mean of
--    the days available so far (ROWS BETWEEN 6 PRECEDING AND CURRENT ROW).
CREATE OR REPLACE VIEW gold.v_daily_trend AS
SELECT
    order_date,
    revenue,
    orders,
    quantity,
    AVG(revenue) OVER (
        ORDER BY order_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS rolling_7d_revenue,
    AVG(revenue) OVER (
        ORDER BY order_date
        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ) AS rolling_30d_revenue,
    LAG(revenue, 1) OVER (ORDER BY order_date) AS revenue_prev_day,
    LAG(revenue, 7) OVER (ORDER BY order_date) AS revenue_7d_ago,
    CASE
        WHEN LAG(revenue, 7) OVER (ORDER BY order_date) IS NULL
            OR LAG(revenue, 7) OVER (ORDER BY order_date) = 0 THEN NULL
        ELSE ROUND(
            100.0 * (revenue - LAG(revenue, 7) OVER (ORDER BY order_date))
            / LAG(revenue, 7) OVER (ORDER BY order_date), 2)
    END AS wow_pct,
    SUM(revenue) OVER (
        ORDER BY order_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_revenue
FROM gold.daily_sales;

-- 2. Monthly trend: month-over-month change, 3-month rolling revenue,
--    cumulative revenue.
CREATE OR REPLACE VIEW gold.v_monthly_trend AS
SELECT
    month,
    revenue,
    orders,
    quantity,
    LAG(revenue, 1) OVER (ORDER BY month) AS revenue_prev_month,
    CASE
        WHEN LAG(revenue, 1) OVER (ORDER BY month) IS NULL
            OR LAG(revenue, 1) OVER (ORDER BY month) = 0 THEN NULL
        ELSE ROUND(
            100.0 * (revenue - LAG(revenue, 1) OVER (ORDER BY month))
            / LAG(revenue, 1) OVER (ORDER BY month), 2)
    END AS mom_pct,
    AVG(revenue) OVER (
        ORDER BY month
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ) AS rolling_3m_revenue,
    SUM(revenue) OVER (
        ORDER BY month
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_revenue
FROM gold.monthly_sales;

-- 3. Top categories: total revenue, share of all revenue, rank,
--    cumulative share (how concentrated revenue is).
CREATE OR REPLACE VIEW gold.v_top_categories AS
SELECT
    category_id,
    SUM(revenue) AS revenue,
    SUM(quantity) AS quantity,
    ROUND(100.0 * SUM(revenue)
        / SUM(SUM(revenue)) OVER (), 2) AS revenue_share_pct,
    RANK() OVER (ORDER BY SUM(revenue) DESC) AS revenue_rank,
    ROUND(100.0 * SUM(SUM(revenue)) OVER (
        ORDER BY SUM(revenue) DESC
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
        / SUM(SUM(revenue)) OVER (), 2) AS cumulative_share_pct
FROM gold.daily_category_sales
GROUP BY category_id;

-- 4. Top stores: same shape as categories, for the store question.
CREATE OR REPLACE VIEW gold.v_top_stores AS
SELECT
    store_id,
    SUM(revenue) AS revenue,
    SUM(quantity) AS quantity,
    ROUND(100.0 * SUM(revenue)
        / SUM(SUM(revenue)) OVER (), 2) AS revenue_share_pct,
    RANK() OVER (ORDER BY SUM(revenue) DESC) AS revenue_rank,
    ROUND(100.0 * SUM(SUM(revenue)) OVER (
        ORDER BY SUM(revenue) DESC
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
        / SUM(SUM(revenue)) OVER (), 2) AS cumulative_share_pct
FROM gold.daily_store_sales
GROUP BY store_id;

-- 5. RFM customers: one row per customer who has ordered.
--    Reference date = latest order_date in Silver (2024-01-01 on
--    the real data), so recency is days since their last order.
--    Scores 1-5 by quintile (NTILE): R high = recent, F high =
--    frequent, M high = high spend. Segments are rule-based and
--    documented below — they are labels, not a model.
DROP TABLE IF EXISTS gold.rfm_customers;
CREATE TABLE gold.rfm_customers AS
WITH customer_stats AS (
    SELECT
        o.customer_id,
        MAX(o.order_date) AS last_order_date,
        COUNT(DISTINCT o.order_id) AS frequency,
        SUM(oi.qty * oi.price) AS monetary,
        ((SELECT MAX(order_date) FROM silver.orders) - MAX(o.order_date)) AS recency_days
    FROM silver.orders o
    JOIN silver.order_items oi ON oi.order_id = o.order_id
    GROUP BY o.customer_id
),
scored AS (
    SELECT
        customer_id,
        last_order_date,
        recency_days,
        frequency,
        monetary,
        6 - NTILE(5) OVER (ORDER BY recency_days ASC) AS r_score,
        NTILE(5) OVER (ORDER BY frequency ASC) AS f_score,
        NTILE(5) OVER (ORDER BY monetary ASC) AS m_score
    FROM customer_stats
)
SELECT
    customer_id,
    last_order_date,
    recency_days,
    frequency,
    monetary,
    r_score,
    f_score,
    m_score,
    (r_score::text || f_score::text || m_score::text) AS rfm_code,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'Champions'
        WHEN f_score >= 4 AND m_score >= 3 THEN 'Loyal Customers'
        WHEN r_score >= 4 AND f_score <= 3 THEN 'Potential Loyalists'
        WHEN r_score <= 2 AND f_score >= 3 THEN 'At Risk'
        WHEN r_score <= 2 AND f_score <= 2 THEN 'Hibernating'
        WHEN r_score = 3 THEN 'Needs Attention'
        ELSE 'Other'
    END AS segment
FROM scored;

-- RFM reference date is (SELECT MAX(order_date) FROM silver.orders),
-- 2024-01-01 on the real data. Customers with no orders are not in
-- rfm_customers; scripts/run_analytics.py reports how many there are.
