-- Grain: Date × Event Type × Device
SELECT
    date_key, -- INT64
    event_key, -- INT64
    device_key, -- INT64
    COUNT(*) AS event_count, -- INT64
    SUM(engagement_time_msec) AS total_engagement_time_msec -- INT64: milliseconds
FROM {{ ref('fct_events') }}
GROUP BY date_key, event_key, device_key