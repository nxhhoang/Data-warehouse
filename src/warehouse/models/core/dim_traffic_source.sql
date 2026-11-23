{{
    config(
        materialized='table'
    )
}}

WITH raw_traffic AS (
    -- 1. Event-level traffic attribution
    SELECT
        source,
        medium,
        campaign
    FROM {{ ref('stg_ga4_events') }}

    UNION DISTINCT

    -- 2. User-level first-touch attribution (ensures full key coverage for dim_user & fallbacks)
    SELECT
        user_first_source AS source,
        user_first_medium AS medium,
        user_first_campaign AS campaign
    FROM {{ ref('stg_ga4_events') }}
),

normalized_traffic AS (
    SELECT DISTINCT
        CASE
            WHEN source IS NULL
              OR TRIM(source) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN '(not set)'
            ELSE LOWER(TRIM(source))
        END AS source,

        CASE
            WHEN medium IS NULL
              OR TRIM(medium) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN '(not set)'
            ELSE LOWER(TRIM(medium))
        END AS medium,

        CASE
            WHEN campaign IS NULL
              OR TRIM(campaign) IN ('', '<Other>', '(data deleted)', '(not set)')
            THEN '(not set)'
            ELSE TRIM(campaign)
        END AS campaign
    FROM raw_traffic
),

dim_traffic_source_base AS (
    SELECT
        {{ gen_sk(['source', 'medium', 'campaign']) }} AS traffic_source_sk,
        source,
        medium,
        campaign,
        {{ map_channel('source', 'medium') }} AS channel_group
    FROM normalized_traffic
)

SELECT * FROM dim_traffic_source_base

UNION ALL

{{ unknown_member(
    sk_col='traffic_source_sk',
    columns=[
        ('source', 'STRING'),
        ('medium', 'STRING'),
        ('campaign', 'STRING'),
        ('channel_group', 'STRING')
    ]
) }}