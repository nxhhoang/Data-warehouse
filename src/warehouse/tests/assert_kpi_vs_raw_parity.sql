-- Milestone M4 Acceptance: Reconcile Marts layer metrics against direct queries on raw source data
WITH mart_agg AS (
    SELECT
        SUM(sessions) AS mart_sessions,
        SUM(orders) AS mart_orders,
        ROUND(SUM(revenue_usd), 2) AS mart_revenue
    FROM {{ ref('fct_daily_ecommerce') }}
),
raw_dedup_orders AS (
    SELECT
        user_pseudo_id,
        ecommerce.transaction_id AS transaction_id,
        ecommerce.purchase_revenue_in_usd AS rev
    FROM {{ source('ga4_raw', 'events') }}
    WHERE _TABLE_SUFFIX BETWEEN '{{ var("start_date") }}' AND '{{ var("end_date") }}'
      AND event_name = 'purchase'
      AND ecommerce.transaction_id IS NOT NULL
      AND TRIM(ecommerce.transaction_id) NOT IN ('(not set)', '<Other>', '(data deleted)', '')
      AND ecommerce.purchase_revenue_in_usd > 0
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY user_pseudo_id, ecommerce.transaction_id
        ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
    ) = 1
),
raw_sessions AS (
    SELECT
        COUNT(DISTINCT CONCAT(
            user_pseudo_id, '_',
            CAST((SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id' LIMIT 1) AS STRING)
        )) AS raw_sessions
    FROM {{ source('ga4_raw', 'events') }}
    WHERE _TABLE_SUFFIX BETWEEN '{{ var("start_date") }}' AND '{{ var("end_date") }}'
)
SELECT
    m.mart_sessions,
    rs.raw_sessions,
    m.mart_orders,
    (SELECT COUNT(*) FROM raw_dedup_orders) AS raw_orders,
    m.mart_revenue,
    (SELECT ROUND(SUM(rev), 2) FROM raw_dedup_orders) AS raw_revenue
FROM mart_agg m
CROSS JOIN raw_sessions rs
WHERE m.mart_sessions != rs.raw_sessions
   OR m.mart_orders != (SELECT COUNT(*) FROM raw_dedup_orders)
   OR ABS(m.mart_revenue - (SELECT SUM(rev) FROM raw_dedup_orders)) > 0.01