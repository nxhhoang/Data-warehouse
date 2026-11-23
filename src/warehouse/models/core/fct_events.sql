{{
    config(
        materialized='table',
        partition_by={
            "field": "event_date",
            "data_type": "date",
            "granularity": "day"
        },
        cluster_by=["event_key", "traffic_source_key"]
    )
}}

WITH staged_events AS (
    SELECT *
    FROM {{ ref('stg_ga4_events') }}
),

valid_orders AS (
    SELECT
        event_id,
        transaction_id,
        purchase_revenue_in_usd
    FROM {{ ref('stg_valid_orders') }}
),

normalized_attributes AS (
    SELECT
        e.*,

        -- 1. Normalize traffic source attributes (matching dim_traffic_source)
        CASE
            WHEN e.source IS NULL
              OR TRIM(e.source) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN '(not set)'
            ELSE LOWER(TRIM(e.source))
        END AS norm_source,

        CASE
            WHEN e.medium IS NULL
              OR TRIM(e.medium) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN '(not set)'
            ELSE LOWER(TRIM(e.medium))
        END AS norm_medium,

        CASE
            WHEN e.campaign IS NULL
              OR TRIM(e.campaign) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN '(not set)'
            ELSE TRIM(e.campaign)
        END AS norm_campaign,

        -- 2. Normalize device attributes (matching dim_device)
        CASE
            WHEN e.device_category IS NULL
              OR TRIM(e.device_category) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN 'Unknown'
            ELSE LOWER(TRIM(e.device_category))
        END AS norm_device_category,

        CASE
            WHEN e.device_os IS NULL
              OR TRIM(e.device_os) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN 'Unknown'
            ELSE TRIM(e.device_os)
        END AS norm_device_os,

        CASE
            WHEN e.device_os_version IS NULL
              OR TRIM(e.device_os_version) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN 'Unknown'
            ELSE TRIM(e.device_os_version)
        END AS norm_device_os_version,

        CASE
            WHEN e.device_brand IS NULL
              OR TRIM(e.device_brand) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN 'Unknown'
            ELSE TRIM(e.device_brand)
        END AS norm_device_brand,

        CASE
            WHEN e.browser IS NULL
              OR TRIM(e.browser) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN 'Unknown'
            ELSE TRIM(e.browser)
        END AS norm_browser,

        -- 3. Normalize geographic attributes (matching dim_geo)
        CASE
            WHEN e.geo_continent IS NULL
              OR TRIM(e.geo_continent) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN 'Unknown'
            ELSE TRIM(e.geo_continent)
        END AS norm_geo_continent,

        CASE
            WHEN e.geo_country IS NULL
              OR TRIM(e.geo_country) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN 'Unknown'
            ELSE TRIM(e.geo_country)
        END AS norm_geo_country,

        CASE
            WHEN e.geo_region IS NULL
              OR TRIM(e.geo_region) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN 'Unknown'
            ELSE TRIM(e.geo_region)
        END AS norm_geo_region,

        CASE
            WHEN e.geo_city IS NULL
              OR TRIM(e.geo_city) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN 'Unknown'
            ELSE TRIM(e.geo_city)
        END AS norm_geo_city,

        -- 4. Extract normalized page_path (matching dim_page)
        CASE
            WHEN e.page_location IS NULL
              OR TRIM(e.page_location) IN ('', '(not set)', '<Other>', '(data deleted)')
              OR NOT REGEXP_CONTAINS(TRIM(e.page_location), r'^https?://[^/]+')
            THEN NULL
            ELSE COALESCE(
                NULLIF(REGEXP_EXTRACT(TRIM(e.page_location), r'^https?://[^/]+(/[^?#]*)'), ''),
                '/'
            )
        END AS norm_page_path,

        -- 5. Validated purchase flags & revenue from stg_valid_orders
        (vo.event_id IS NOT NULL) AS is_valid_purchase,
        COALESCE(vo.purchase_revenue_in_usd, 0.0) AS valid_purchase_revenue_in_usd

    FROM staged_events AS e
    LEFT JOIN valid_orders AS vo
        ON e.event_id = vo.event_id
)

SELECT
    -- 1. Primary Key
    event_id,

    -- 2. Foreign Keys to Dimensions (guaranteed non-null via -1 unknown_member fallback)
    COALESCE(CAST(FORMAT_DATE('%Y%m%d', event_date) AS INT64), -1) AS date_key,

    CASE
        WHEN event_name IS NULL
          OR TRIM(event_name) IN ('', '(not set)', '<Other>', '(data deleted)')
        THEN -1
        ELSE {{ gen_sk(['TRIM(event_name)']) }}
    END AS event_key,

    CASE
        WHEN user_pseudo_id IS NULL
          OR TRIM(user_pseudo_id) IN ('', '(not set)', '<Other>', '(data deleted)')
        THEN -1
        ELSE {{ gen_sk(['user_pseudo_id']) }}
    END AS user_sk,

    COALESCE(
        {{ gen_sk(['norm_source', 'norm_medium', 'norm_campaign']) }},
        -1
    ) AS traffic_source_key,

    CASE
        WHEN norm_device_category = 'Unknown'
         AND norm_device_os = 'Unknown'
         AND norm_device_os_version = 'Unknown'
         AND norm_device_brand = 'Unknown'
         AND norm_browser = 'Unknown'
        THEN -1
        ELSE {{ gen_sk([
            'norm_device_category',
            'norm_device_os',
            'norm_device_os_version',
            'norm_device_brand',
            'norm_browser'
        ]) }}
    END AS device_sk,

    CASE
        WHEN norm_geo_continent = 'Unknown'
         AND norm_geo_country = 'Unknown'
         AND norm_geo_region = 'Unknown'
         AND norm_geo_city = 'Unknown'
        THEN -1
        ELSE {{ gen_sk([
            'norm_geo_continent',
            'norm_geo_country',
            'norm_geo_region',
            'norm_geo_city'
        ]) }}
    END AS geo_sk,

    CASE
        WHEN norm_page_path IS NULL THEN -1
        ELSE {{ gen_sk(['norm_page_path']) }}
    END AS page_sk,

    -- 3. Session & Degenerate Dimensions
    CASE
        WHEN ga_session_id IS NOT NULL
        THEN {{ gen_sk(['user_pseudo_id', 'ga_session_id']) }}
        ELSE -1
    END AS session_id,

    ga_session_id,
    event_date,
    event_ts,
    event_timestamp,
    event_bundle_sequence_id,
    COALESCE(NULLIF(TRIM(transaction_id), ''), 'Unknown') AS transaction_id,

    -- 4. Event Behavioral Flags & Additive Measures
    (COALESCE(engaged_session_event, 0) = 1 OR session_engaged = '1') AS is_engaged_session_event,
    is_valid_purchase,
    COALESCE(engagement_time_msec, 0) AS engagement_time_msec,
    COALESCE(event_value_in_usd, 0.0) AS event_value_in_usd,
    valid_purchase_revenue_in_usd AS purchase_revenue_in_usd

FROM normalized_attributes