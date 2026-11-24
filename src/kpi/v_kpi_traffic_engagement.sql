-- Group A: Traffic and Engagement (Report Table 6)
CREATE OR REPLACE VIEW `${PROJECT_ID}.kpi.v_kpi_traffic_engagement` AS
WITH daily_slice AS (
    SELECT
        d.full_date AS event_date,
        d.year_month,
        d.is_weekend,
        ts.channel_group,
        ts.source,
        ts.medium,
        ts.campaign,
        ts.is_unassigned,
        dev.device_category,
        SUM(f.sessions) AS sessions,
        SUM(f.engaged_sessions) AS engaged_sessions,
        SUM(f.page_views) AS page_views,
        SUM(f.engagement_time_msec) AS engagement_time_msec
    FROM `${PROJECT_ID}.marts.fct_daily_ecommerce` f
    JOIN `${PROJECT_ID}.core.dim_date` d ON f.date_key = d.date_key
    JOIN `${PROJECT_ID}.core.dim_traffic_source` ts ON f.session_source_key = ts.traffic_source_key
    JOIN `${PROJECT_ID}.core.dim_device` dev ON f.device_key = dev.device_key
    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
),
daily_users AS (
    -- Users & new users queried from fct_sessions to avoid cross-device double-counting
    SELECT
        d.full_date AS event_date,
        ts.channel_group,
        ts.source,
        ts.medium,
        ts.campaign,
        dev.device_category,
        COUNT(DISTINCT s.user_key) AS users,
        COUNT(DISTINCT CASE WHEN u.is_new_user THEN s.user_key END) AS new_users
    FROM `${PROJECT_ID}.core.fct_sessions` s
    JOIN `${PROJECT_ID}.core.dim_date` d ON s.date_key = d.date_key
    JOIN `${PROJECT_ID}.core.dim_user` u ON s.user_key = u.user_key
    JOIN `${PROJECT_ID}.core.dim_traffic_source` ts ON s.session_source_key = ts.traffic_source_key
    JOIN `${PROJECT_ID}.core.dim_device` dev ON s.device_key = dev.device_key
    GROUP BY 1, 2, 3, 4, 5, 6
)
SELECT
    ds.*,
    COALESCE(du.users, 0) AS users,
    COALESCE(du.new_users, 0) AS new_users,
    SAFE_DIVIDE(ds.sessions, du.users) AS sessions_per_user,
    SAFE_DIVIDE(ds.engaged_sessions, ds.sessions) AS engagement_rate,
    SAFE_DIVIDE(du.new_users, du.users) AS new_user_rate
FROM daily_slice ds
LEFT JOIN daily_users du
    ON ds.event_date = du.event_date
    AND ds.channel_group = du.channel_group
    AND ds.source = du.source
    AND ds.medium = du.medium
    AND ds.campaign = du.campaign
    AND ds.device_category = du.device_category;