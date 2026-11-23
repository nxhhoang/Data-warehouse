{{
    config(
        materialized='table'
    )
}}

WITH clean_user_events AS (
    SELECT
        user_pseudo_id,
        NULLIF(TRIM(user_id), '') AS user_id,
        event_date,
        event_timestamp,
        event_ts,
        event_bundle_sequence_id,
        event_name,
        user_first_touch_timestamp,
        COALESCE(
            NULLIF(TRIM(user_first_source), ''),
            NULLIF(TRIM(source), '')
        ) AS raw_first_source,
        COALESCE(
            NULLIF(TRIM(user_first_medium), ''),
            NULLIF(TRIM(medium), '')
        ) AS raw_first_medium,
        COALESCE(
            NULLIF(TRIM(user_first_campaign), ''),
            NULLIF(TRIM(campaign), '')
        ) AS raw_first_campaign
    FROM {{ ref('stg_ga4_events') }}
    WHERE user_pseudo_id IS NOT NULL
      AND TRIM(user_pseudo_id) NOT IN ('', '(not set)', '<Other>', '(data deleted)')
),

-- 1. Extract attribution & initial touchpoint from the earliest event per user
first_touch_events AS (
    SELECT
        user_pseudo_id,
        COALESCE(
            TIMESTAMP_MICROS(user_first_touch_timestamp),
            event_ts
        ) AS first_touch_ts,

        CASE
            WHEN raw_first_source IS NULL
              OR raw_first_source IN ('<Other>', '(data deleted)', '(not set)')
            THEN '(not set)'
            ELSE LOWER(raw_first_source)
        END AS first_source,

        CASE
            WHEN raw_first_medium IS NULL
              OR raw_first_medium IN ('<Other>', '(data deleted)', '(not set)')
            THEN '(not set)'
            ELSE LOWER(raw_first_medium)
        END AS first_medium,

        CASE
            WHEN raw_first_campaign IS NULL
              OR raw_first_campaign IN ('<Other>', '(data deleted)', '(not set)')
            THEN '(not set)'
            ELSE raw_first_campaign
        END AS first_campaign

    FROM clean_user_events
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY user_pseudo_id
        ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
    ) = 1
),

-- 2. Aggregate user-level lifecycle & conversion attributes across all events
user_lifecycle AS (
    SELECT
        user_pseudo_id,
        COALESCE(
            MAX(IF(user_id IN ('(not set)', '<Other>', '(data deleted)'), NULL, user_id)),
            'Unknown'
        ) AS user_id,
        MIN(event_date) AS first_seen_date,
        MAX(event_date) AS last_seen_date,
        LOGICAL_OR(event_name = 'purchase') AS is_purchaser
    FROM clean_user_events
    GROUP BY user_pseudo_id
),

dim_user_base AS (
    SELECT
        {{ gen_sk(['ft.user_pseudo_id']) }} AS user_sk,
        ft.user_pseudo_id,
        ul.user_id,
        ft.first_source,
        ft.first_medium,
        ft.first_campaign,
        {{ map_channel('ft.first_source', 'ft.first_medium') }} AS first_channel_group,
        ul.first_seen_date,
        ul.last_seen_date,
        ft.first_touch_ts,
        ul.is_purchaser
    FROM first_touch_events AS ft
    INNER JOIN user_lifecycle AS ul
        ON ft.user_pseudo_id = ul.user_pseudo_id
)

SELECT * FROM dim_user_base

UNION ALL

{{ unknown_member(
    sk_col='user_sk',
    columns=[
        ('user_pseudo_id', 'STRING'),
        ('user_id', 'STRING'),
        ('first_source', 'STRING'),
        ('first_medium', 'STRING'),
        ('first_campaign', 'STRING'),
        ('first_channel_group', 'STRING'),
        ('first_seen_date', 'DATE'),
        ('last_seen_date', 'DATE'),
        ('first_touch_ts', 'TIMESTAMP'),
        ('is_purchaser', 'BOOL')
    ]
) }}