-- Filter valid transactions per Section 3.4 of the report and config/quality_rules.yaml:
-- transaction_id is not NULL, not '(not set)'/placeholders, and revenue > 0;
-- if duplicate (user_pseudo_id, transaction_id) pairs exist, keep the event with the earliest event_timestamp.
SELECT
    event_id,
    session_id,
    user_pseudo_id,
    transaction_id,
    event_date,
    date_key,
    event_timestamp,
    event_ts_utc,
    event_bundle_sequence_id,
    purchase_revenue_in_usd AS revenue_usd,
    COALESCE(total_item_quantity, 0) AS total_item_quantity
FROM {{ ref('stg_ga4_events') }}
WHERE event_name = 'purchase'
  AND transaction_id IS NOT NULL
  AND transaction_id NOT IN ('(not set)', '<Other>', '(data deleted)', '')
  AND purchase_revenue_in_usd IS NOT NULL
  AND purchase_revenue_in_usd > 0
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY user_pseudo_id, transaction_id
    ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
) = 1