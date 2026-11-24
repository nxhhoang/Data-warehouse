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
),
daily_users AS (
    -- Users counted from fct_sessions to avoid cross-device double counting
    SELECT
        d.full_date AS event_date,
        ts.channel_group,
        ts.source,
        ts.medium,
        ts.campaign,
        dev.device_category,
        COUNT(DISTINCT s.user_key) AS users
    FROM `${PROJECT_ID}.core.fct_sessions` s
    JOIN `${PROJECT_ID}.core.dim_date` d ON s.date_key = d.date_key
    JOIN `${PROJECT_ID}.core.dim_traffic_source` ts ON s.session_source_key = ts.traffic_source_key
    JOIN `${PROJECT_ID}.core.dim_device` dev ON s.device_key = dev.device_key
    GROUP BY 1, 2, 3, 4, 5, 6
)
SELECT
    a.*,
    COALESCE(u.users, 0) AS users,
    SAFE_DIVIDE(a.purchasing_sessions, a.sessions) AS conversion_rate,
    SAFE_DIVIDE(a.revenue_usd, a.orders) AS aov_usd,
    SAFE_DIVIDE(a.revenue_usd, a.sessions) AS revenue_per_session_usd,
    SAFE_DIVIDE(a.revenue_usd, u.users) AS revenue_per_user_usd,
    SAFE_DIVIDE(a.revenue_usd, SUM(a.revenue_usd) OVER ()) AS revenue_share_total
FROM agg a
LEFT JOIN daily_users u
    ON a.event_date = u.event_date
    AND a.channel_group = u.channel_group
    AND a.source = u.source
    AND a.medium = u.medium
    AND a.campaign = u.campaign
    AND a.device_category = u.device_category;
