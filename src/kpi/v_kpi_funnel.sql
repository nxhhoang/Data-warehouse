-- Group B: Conversion Funnel and Purchasing Behavior (Report Table 7)
CREATE OR REPLACE VIEW `${PROJECT_ID}.kpi.v_kpi_funnel` AS
SELECT
    d.full_date AS event_date,
    d.year_month,
    d.is_add_to_cart_tracked,
    ts.channel_group,
    ts.source,
    ts.medium,
    ts.campaign,
    dev.device_category,
    SUM(f.view_item_events) AS view_item_events,
    SUM(f.sessions) AS total_sessions,
    SUM(f.sessions_with_view_item) AS sessions_with_view_item,
    SUM(f.sessions_with_add_to_cart) AS sessions_with_add_to_cart,
    SUM(f.sessions_with_begin_checkout) AS sessions_with_begin_checkout,
    SUM(f.sessions_with_purchase) AS sessions_with_purchase,
    SUM(f.sessions_cart_and_purchase) AS sessions_cart_and_purchase,
    SUM(f.sessions_checkout_and_purchase) AS sessions_checkout_and_purchase,
    -- Funnel step transition rates (when aggregating across multiple days on the Dashboard, recalculate from numerators/denominators)
    SAFE_DIVIDE(SUM(f.sessions_with_add_to_cart), SUM(f.sessions_with_view_item)) AS add_to_cart_rate,
    SAFE_DIVIDE(SUM(f.sessions_with_begin_checkout), SUM(f.sessions_with_add_to_cart)) AS begin_checkout_rate,
    SAFE_DIVIDE(SUM(f.sessions_checkout_and_purchase), SUM(f.sessions_with_begin_checkout)) AS purchase_completion_rate,
    1 - SAFE_DIVIDE(SUM(f.sessions_cart_and_purchase), SUM(f.sessions_with_add_to_cart)) AS cart_abandonment_rate
FROM `${PROJECT_ID}.marts.fct_daily_ecommerce` f
JOIN `${PROJECT_ID}.core.dim_date` d ON f.date_key = d.date_key
JOIN `${PROJECT_ID}.core.dim_traffic_source` ts ON f.session_source_key = ts.traffic_source_key
JOIN `${PROJECT_ID}.core.dim_device` dev ON f.device_key = dev.device_key
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8;