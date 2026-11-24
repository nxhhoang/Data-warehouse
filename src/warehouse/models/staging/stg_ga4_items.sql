SELECT
    e.event_id,
    e.session_id,
    e.user_pseudo_id,
    e.event_name,
    e.event_date,
    e.date_key,
    e.event_timestamp,
    e.transaction_id,
    item_pos,
    NULLIF(TRIM(it.item_id), '') AS item_id,
    NULLIF(TRIM(it.item_name), '') AS item_name,
    NULLIF(TRIM(it.item_brand), '') AS item_brand,
    NULLIF(TRIM(it.item_variant), '') AS item_variant,
    NULLIF(TRIM(it.item_category), '') AS item_category,
    NULLIF(TRIM(it.item_category2), '') AS item_category2,
    NULLIF(TRIM(it.item_category3), '') AS item_category3,
    -- Per Survey 08: default quantity = 1 if not set in GA4
    COALESCE(it.quantity, 1) AS quantity,
    COALESCE(it.price_in_usd, it.price, 0.0) AS price_usd,
    COALESCE(it.item_revenue_in_usd, it.item_revenue, 0.0) AS item_revenue_usd
FROM {{ ref('stg_ga4_events') }} e
CROSS JOIN UNNEST(e.items) AS it WITH OFFSET AS item_pos
WHERE e.event_name IN ('view_item', 'select_item', 'add_to_cart', 'begin_checkout', 'purchase')