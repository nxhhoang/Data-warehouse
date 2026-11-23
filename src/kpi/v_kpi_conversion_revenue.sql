-- Group C: Conversion and Revenue (Report Table 8)
CREATE OR REPLACE VIEW `${PROJECT_ID}.kpi.v_kpi_conversion_revenue` AS
WITH agg AS (
    SELECT
        d.full_date AS event_date,
        d.year_month,
        ts.channel_group,
        ts.source,
        ts.medium,
        ts.campaign,
        ts.is_unassigned,
        dev.device_category,
        SUM(f.sessions) AS sessions,
        SUM(f.sessions_with_purchase) AS purchasing_sessions,
        SUM(f.orders) AS orders,
        SUM(f.revenue_usd) AS revenue_usd
    FROM `${PROJECT_ID}.marts.fct_daily_ecommerce` f
    JOIN `${PROJECT_ID}.core.dim_date` d ON f.date_key = d.date_key
    JOIN `${PROJECT_ID}.core.dim_traffic_source` ts ON f.session_source_key = ts.traffic_source_key
    JOIN `${PROJECT_ID}.core.dim_device` dev ON f.device_key = dev.device_key
    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
)
SELECT
    *,
    SAFE_DIVIDE(purchasing_sessions, sessions) AS conversion_rate,
    SAFE_DIVIDE(revenue_usd, orders) AS aov_usd,
    SAFE_DIVIDE(revenue_usd, sessions) AS revenue_per_session_usd,
    SAFE_DIVIDE(revenue_usd, SUM(revenue_usd) OVER ()) AS revenue_share_total
FROM agg;