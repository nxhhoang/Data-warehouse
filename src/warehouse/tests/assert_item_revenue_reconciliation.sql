-- Reconcile item-level transformation from stg_ga4_items to fct_purchase_items.
-- The contract applies at (user_key, transaction_id), not as a global row/money sum.
-- Keep positive source item revenue; otherwise derive price_usd * quantity.
--
-- Order-level purchase_revenue_in_usd is an independent, obfuscated GA4 measure.
-- It need not exactly equal item revenue, so it is shown as a diagnostic column,
-- not used to judge whether the source-item -> fact-item transformation is correct.
-- Count mismatches and a source vs fact discrepancy over $0.01 fail this test.
-- A valid order with no source items must not be given fabricated fact item rows.
--
-- Diagnostic gaps belong in the quality report. They are distinct from the ETL
-- failures returned by this test.
WITH source_item_totals AS (
    SELECT
        event_id,
        COUNT(*) AS item_rows,
        SUM(
            CASE
                WHEN item_revenue_usd > 0 THEN item_revenue_usd
                ELSE price_usd * quantity
            END
        ) AS item_revenue
    FROM {{ ref('stg_ga4_items') }}
    WHERE event_name = 'purchase'
    GROUP BY event_id
),
item_totals AS (
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
    COALESCE(s.item_rows, 0) AS source_item_rows,
    COALESCE(i.item_rows, 0) AS fact_item_rows,
    ROUND(COALESCE(s.item_revenue, 0.0), 2) AS source_item_revenue,
    ROUND(COALESCE(i.item_revenue, 0.0), 2) AS fact_item_revenue,
    ROUND(COALESCE(s.item_revenue, 0.0) - COALESCE(i.item_revenue, 0.0), 2) AS source_to_fact_gap,
    ROUND(o.revenue_usd - COALESCE(s.item_revenue, 0.0), 2) AS order_vs_source_gap
FROM {{ ref('stg_valid_orders') }} o
LEFT JOIN source_item_totals s
    ON o.event_id = s.event_id
LEFT JOIN {{ ref('dim_user') }} u
    ON o.user_pseudo_id = u.user_pseudo_id
LEFT JOIN item_totals i
    ON i.user_key = COALESCE(u.user_key, -1)
    AND i.transaction_id = o.transaction_id
WHERE COALESCE(i.item_rows, 0) != COALESCE(s.item_rows, 0)
   OR ABS(COALESCE(s.item_revenue, 0.0) - COALESCE(i.item_revenue, 0.0)) > 0.01
