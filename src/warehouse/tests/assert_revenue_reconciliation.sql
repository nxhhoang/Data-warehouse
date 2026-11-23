-- Milestone M3 Acceptance: Reconcile total revenue and order count between fct_sessions and stg_valid_orders
WITH session_totals AS (
    SELECT
        SUM(order_count) AS session_orders,
        ROUND(SUM(revenue_usd), 2) AS session_revenue
    FROM {{ ref('fct_sessions') }}
),
order_totals AS (
    SELECT
        COUNT(*) AS valid_orders,
        ROUND(SUM(revenue_usd), 2) AS valid_revenue
    FROM {{ ref('stg_valid_orders') }}
)
SELECT
    s.session_orders,
    o.valid_orders,
    s.session_revenue,
    o.valid_revenue
FROM session_totals s
CROSS JOIN order_totals o
WHERE s.session_orders != o.valid_orders
   OR ABS(s.session_revenue - o.valid_revenue) > 0.01