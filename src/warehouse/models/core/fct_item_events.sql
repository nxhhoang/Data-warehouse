SELECT
    {{ gen_sk(['i.event_id', 'i.item_pos']) }} AS item_event_id, -- INT64
    COALESCE(fe.date_key, -1) AS date_key, -- INT64
    COALESCE(fe.event_key, -1) AS event_key, -- INT64
    COALESCE(fe.user_key, -1) AS user_key, -- INT64
    COALESCE(fe.device_key, -1) AS device_key, -- INT64
    COALESCE(fe.geo_key, -1) AS geo_key, -- INT64
    COALESCE(fe.traffic_source_key, -1) AS traffic_source_key, -- INT64
    COALESCE(p.product_key, -1) AS product_key, -- INT64
    COALESCE(i.session_id, 'Unknown') AS session_id, -- STRING
    i.quantity -- INT64
FROM {{ ref('stg_ga4_items') }} i
LEFT JOIN {{ ref('fct_events') }} fe ON i.event_id = fe.event_id
LEFT JOIN {{ ref('dim_product') }} p ON i.item_id = p.item_id
WHERE i.event_name IN ('view_item', 'select_item', 'add_to_cart', 'begin_checkout')