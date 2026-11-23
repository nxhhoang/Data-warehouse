-- Grain: Date × Session Source × Device
-- Store only additive numerators and denominators (Report Section 4.5)
SELECT
    date_key,
    session_source_key,
    device_key,
    COUNT(*) AS sessions,
    SUM(is_engaged) AS engaged_sessions,
    SUM(page_view_count) AS page_views,
    SUM(view_item_count) AS view_item_events,
    SUM(engagement_time_msec) AS engagement_time_msec,
    SUM(has_view_item) AS sessions_with_view_item,
    SUM(has_add_to_cart) AS sessions_with_add_to_cart,
    SUM(has_begin_checkout) AS sessions_with_begin_checkout,
    SUM(has_purchase) AS sessions_with_purchase,
    SUM(CASE WHEN has_add_to_cart = 1 AND has_purchase = 1 THEN 1 ELSE 0 END) AS sessions_cart_and_purchase,
    SUM(CASE WHEN has_begin_checkout = 1 AND has_purchase = 1 THEN 1 ELSE 0 END) AS sessions_checkout_and_purchase,
    SUM(order_count) AS orders,
    SUM(revenue_usd) AS revenue_usd
FROM {{ ref('fct_sessions') }}
GROUP BY date_key, session_source_key, device_key