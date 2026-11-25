-- Grain: Date × Session Source × Device
-- Store only additive numerators and denominators (Report Section 4.5)
SELECT
    date_key, -- INT64
    session_source_key, -- INT64
    device_key, -- INT64
    COUNT(*) AS sessions, -- INT64
    SUM(is_engaged) AS engaged_sessions, -- INT64
    SUM(page_view_count) AS page_views, -- INT64
    SUM(view_item_count) AS view_item_events, -- INT64
    SUM(engagement_time_msec) AS engagement_time_msec, -- INT64: milliseconds
    SUM(has_view_item) AS sessions_with_view_item, -- INT64
    SUM(has_add_to_cart) AS sessions_with_add_to_cart, -- INT64
    SUM(has_begin_checkout) AS sessions_with_begin_checkout, -- INT64
    SUM(has_add_shipping_info) AS sessions_with_add_shipping_info, -- INT64
    SUM(has_add_payment_info) AS sessions_with_add_payment_info, -- INT64
    SUM(has_purchase) AS sessions_with_purchase, -- INT64
    SUM(CASE WHEN has_add_to_cart = 1 AND has_purchase = 1 THEN 1 ELSE 0 END) AS sessions_cart_and_purchase, -- INT64
    SUM(CASE WHEN has_begin_checkout = 1 AND has_purchase = 1 THEN 1 ELSE 0 END) AS sessions_checkout_and_purchase, -- INT64
    SUM(CASE WHEN has_add_payment_info = 1 AND has_purchase = 1 THEN 1 ELSE 0 END) AS sessions_payment_and_purchase, -- INT64
    SUM(order_count) AS orders, -- INT64
    SUM(revenue_usd) AS revenue_usd -- FLOAT64: US dollars
FROM {{ ref('fct_sessions') }}
GROUP BY date_key, session_source_key, device_key