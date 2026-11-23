-- Reconcile item-level revenue (fct_purchase_items) against order-level revenue
-- (stg_valid_orders), as promised in report Section 4.5:
-- "Doanh thu cấp phiên (fct_sessions) và tổng item_revenue_usd (fct_purchase_items)
-- được đối chiếu bằng kiểm thử dbt; chênh lệch được ghi vào nhật ký chất lượng dữ liệu."
-- Together with assert_revenue_reconciliation.sql (fct_sessions vs stg_valid_orders),
-- this closes the chain: fct_sessions <-> stg_valid_orders <-> fct_purchase_items.
--
-- Join key: (user_key, transaction_id). fct_purchase_items does not carry
-- user_pseudo_id, so match through dim_user the same way fct_events builds user_key
-- (COALESCE to -1 for users absent from dim_user, e.g. blank user_pseudo_id).
--
-- Any returned row is a transaction whose summed item revenue (including the
-- price * quantity fallback) does not match the order revenue within $0.01,
-- or an order that has no item rows at all. Record failures in data/quality_log/.
WITH item_totals AS (
    SELECT
        user_key,
        transaction_id,
        COUNT(*) AS item_rows,
        SUM(item_revenue_usd) AS item_revenue
    FROM {{ ref('fct_purchase_items') }}
    GROUP BY user_key, transaction_id
)
SELECT
    o.user_pseudo_id,
    o.transaction_id,
    o.revenue_usd AS order_revenue,
    COALESCE(i.item_rows, 0) AS item_rows,
    ROUND(COALESCE(i.item_revenue, 0.0), 2) AS item_revenue,
    ROUND(o.revenue_usd - COALESCE(i.item_revenue, 0.0), 2) AS revenue_gap
FROM {{ ref('stg_valid_orders') }} o
LEFT JOIN {{ ref('dim_user') }} u
    ON o.user_pseudo_id = u.user_pseudo_id
LEFT JOIN item_totals i
    ON i.user_key = COALESCE(u.user_key, -1)
    AND i.transaction_id = o.transaction_id
WHERE ABS(o.revenue_usd - COALESCE(i.item_revenue, 0.0)) > 0.01
