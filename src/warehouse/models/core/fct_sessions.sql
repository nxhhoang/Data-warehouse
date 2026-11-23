{{
    config(
        materialized='table',
        partition_by={
            "field": "session_date",
            "data_type": "date",
            "granularity": "day"
        },
        cluster_by=["effective_traffic_source_key", "user_sk"]
    )
}}

WITH session_events AS (
    SELECT
        e.event_id,
        e.session_id,
        e.ga_session_id,
        e.user_sk,
        e.traffic_source_key,
        e.device_sk,
        e.geo_sk,
        e.page_sk,
        e.event_date,
        e.event_ts,
        e.event_timestamp,
        e.event_bundle_sequence_id,
        e.is_engaged_session_event,
        e.is_valid_purchase,
        e.engagement_time_msec,
        e.event_value_in_usd,
        e.purchase_revenue_in_usd,
        de.event_name,
        ts.source AS event_source,
        ts.medium AS event_medium
    FROM {{ ref('fct_events') }} AS e
    LEFT JOIN {{ ref('dim_event') }} AS de
        ON e.event_key = de.event_key
    LEFT JOIN {{ ref('dim_traffic_source') }} AS ts
        ON e.traffic_source_key = ts.traffic_source_sk
    WHERE e.session_id != -1
),

session_windowed AS (
    SELECT
        *,

        -- First valid non-'(not set)' traffic source within the session
        FIRST_VALUE(
            IF(
                traffic_source_key != -1
                AND (event_source != '(not set)' OR event_medium != '(not set)'),
                traffic_source_key,
                NULL
            ) IGNORE NULLS
        ) OVER (
            PARTITION BY session_id
            ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS first_valid_session_source_key,

        -- Initial device, geography, and landing/exit pages in chronological order
        FIRST_VALUE(NULLIF(device_sk, -1) IGNORE NULLS) OVER (
            PARTITION BY session_id
            ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS first_device_sk,

        FIRST_VALUE(NULLIF(geo_sk, -1) IGNORE NULLS) OVER (
            PARTITION BY session_id
            ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS first_geo_sk,

        FIRST_VALUE(NULLIF(page_sk, -1) IGNORE NULLS) OVER (
            PARTITION BY session_id
            ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS first_page_sk,

        LAST_VALUE(NULLIF(page_sk, -1) IGNORE NULLS) OVER (
            PARTITION BY session_id
            ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS last_page_sk

    FROM session_events
),

session_aggregated AS (
    SELECT
        -- 1. Primary Key & Natural Session ID
        session_id,
        ANY_VALUE(ga_session_id) AS ga_session_id,

        -- 2. Anchor midnight-spanning sessions to the start date (MIN(event_date))
        MIN(event_date) AS session_date,
        COALESCE(CAST(FORMAT_DATE('%Y%m%d', MIN(event_date)) AS INT64), -1) AS date_key,

        -- 3. Core Dimension Foreign Keys
        COALESCE(ANY_VALUE(user_sk), -1) AS user_sk,
        COALESCE(ANY_VALUE(first_valid_session_source_key), -1) AS session_source_key,
        COALESCE(ANY_VALUE(first_device_sk), -1) AS device_sk,
        COALESCE(ANY_VALUE(first_geo_sk), -1) AS geo_sk,
        COALESCE(ANY_VALUE(first_page_sk), -1) AS landing_page_sk,
        COALESCE(ANY_VALUE(last_page_sk), -1) AS exit_page_sk,

        -- 4. Session Timestamps & Engagement Duration
        MIN(event_ts) AS session_start_ts,
        MAX(event_ts) AS session_end_ts,
        TIMESTAMP_DIFF(MAX(event_ts), MIN(event_ts), SECOND) AS session_duration_sec,
        SUM(engagement_time_msec) AS total_engagement_time_msec,

        -- 5. Cumulative Funnel Flags (0/1)
        MAX(CASE WHEN is_engaged_session_event THEN 1 ELSE 0 END) AS is_engaged,
        MAX(CASE WHEN event_name = 'view_item' THEN 1 ELSE 0 END) AS has_view_item,
        MAX(CASE WHEN event_name = 'add_to_cart' THEN 1 ELSE 0 END) AS has_add_to_cart,
        MAX(CASE WHEN event_name = 'begin_checkout' THEN 1 ELSE 0 END) AS has_begin_checkout,
        MAX(CASE WHEN is_valid_purchase THEN 1 ELSE 0 END) AS has_purchase,

        -- 6. Additive Session Volume & Revenue Measures
        COUNT(*) AS event_count,
        COUNTIF(event_name = 'page_view') AS pageview_count,
        COUNTIF(is_valid_purchase) AS valid_order_count,
        SUM(purchase_revenue_in_usd) AS purchase_revenue_in_usd,
        SUM(event_value_in_usd) AS event_value_in_usd

    FROM session_windowed
    GROUP BY session_id
),

final_sessions AS (
    SELECT
        sa.session_id,
        sa.ga_session_id,
        sa.session_date,
        sa.date_key,
        sa.user_sk,

        -- Two-tier attribution keys (Role-playing with dim_traffic_source)
        sa.session_source_key,

        CASE
            WHEN du.user_sk IS NULL OR du.user_sk = -1 THEN -1
            ELSE {{ gen_sk(['du.first_source', 'du.first_medium', 'du.first_campaign']) }}
        END AS user_source_key,

        COALESCE(
            NULLIF(sa.session_source_key, -1),
            CASE
                WHEN du.user_sk IS NULL OR du.user_sk = -1 THEN -1
                ELSE {{ gen_sk(['du.first_source', 'du.first_medium', 'du.first_campaign']) }}
            END,
            -1
        ) AS effective_traffic_source_key,

        CASE
            WHEN sa.session_source_key != -1 THEN 'session'
            ELSE 'user_fallback'
        END AS attribution_basis,

        sa.device_sk,
        sa.geo_sk,
        sa.landing_page_sk,
        sa.exit_page_sk,
        sa.session_start_ts,
        sa.session_end_ts,
        sa.session_duration_sec,
        sa.total_engagement_time_msec,
        sa.is_engaged,
        sa.has_view_item,
        sa.has_add_to_cart,
        sa.has_begin_checkout,
        sa.has_purchase,
        sa.event_count,
        sa.pageview_count,
        sa.valid_order_count,
        sa.purchase_revenue_in_usd,
        sa.event_value_in_usd

    FROM session_aggregated AS sa
    LEFT JOIN {{ ref('dim_user') }} AS du
        ON sa.user_sk = du.user_sk
)

SELECT * FROM final_sessions