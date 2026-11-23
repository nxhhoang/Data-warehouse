SELECT
    {{ gen_sk(['i.event_id', 'i.item_pos']) }} AS item_event_id,
    COALESCE(fe.date_key, -1) AS date_key,
    COALESCE(fe.event_key, -1) AS event_key,
    COALESCE(fe.user_key, -1) AS user_key,
    COALESCE(fe.device_key, -1) AS device_key,
    COALESCE(fe.geo_key, -1) AS geo_key,
    COALESCE(fe.traffic_source_key, -1) AS traffic_source_key,
    COALESCE(p.product_key, -1) AS product_key,
    COALESCE(i.session_id, 'Unknown') AS session_id,
    i.quantity
FROM {{ ref('stg_ga4_items') }} i
LEFT JOIN {{ ref('fct_events') }} fe ON i.event_id = fe.event_id
LEFT JOIN {{ ref('dim_product') }} p ON i.item_id = p.item_id
WHERE i.event_name IN ('view_item', 'select_item', 'add_to_cart', 'begin_checkout')