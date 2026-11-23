-- Grain: Date × Event Type × Device
SELECT
    date_key,
    event_key,
    device_key,
    COUNT(*) AS event_count,
    SUM(engagement_time_msec) AS total_engagement_time_msec
FROM {{ ref('fct_events') }}
GROUP BY date_key, event_key, device_key