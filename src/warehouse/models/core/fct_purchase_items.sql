SELECT
    {{ gen_sk(['i.event_id', 'i.item_pos']) }} AS purchase_item_id, -- INT64
    COALESCE(fe.date_key, -1) AS date_key, -- INT64
    COALESCE(fe.user_key, -1) AS user_key, -- INT64
    COALESCE(fe.device_key, -1) AS device_key, -- INT64
    COALESCE(fe.geo_key, -1) AS geo_key, -- INT64
    COALESCE(fe.traffic_source_key, -1) AS traffic_source_key, -- INT64
    COALESCE(p.product_key, -1) AS product_key, -- INT64
    COALESCE(o.session_id, 'Unknown') AS session_id, -- STRING
    o.transaction_id, -- STRING
    i.quantity, -- INT64
    i.price_usd, -- FLOAT64: US dollars
    -- If the item row lacks item_revenue_usd but has price_usd, calculate fallback as price_usd * quantity
    CASE
        WHEN i.item_revenue_usd > 0 THEN i.item_revenue_usd
        ELSE i.price_usd * i.quantity
    END AS item_revenue_usd -- FLOAT64: US dollars
FROM {{ ref('stg_valid_orders') }} o
JOIN {{ ref('stg_ga4_items') }} i
    ON o.event_id = i.event_id
    AND i.event_name = 'purchase'
LEFT JOIN {{ ref('fct_events') }} fe ON o.event_id = fe.event_id
LEFT JOIN {{ ref('dim_product') }} p ON i.item_id = p.item_id