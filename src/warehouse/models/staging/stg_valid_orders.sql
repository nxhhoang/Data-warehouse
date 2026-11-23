{{
    config(
        materialized='view'
    )
}}

WITH raw_purchases AS (
    SELECT
        event_id,
        event_date,
        event_timestamp,
        event_ts,
        event_bundle_sequence_id,
        user_pseudo_id,
        user_id,
        ga_session_id,
        transaction_id,
        purchase_revenue_in_usd,
        total_item_quantity,
        page_location,
        source,
        medium,
        campaign,
        user_first_source,
        user_first_medium,
        user_first_campaign,
        device_category,
        device_os,
        browser,
        geo_country,
        geo_city,
        items
    FROM {{ ref('stg_ga4_events') }}
    WHERE event_name = 'purchase'
),

valid_orders AS (
    SELECT
        -- Deterministic surrogate key for unique valid order
        {{ gen_sk(['user_pseudo_id', 'transaction_id']) }} AS order_sk,
        *
    FROM raw_purchases
    WHERE
        -- Rule 1: Drop purchases missing a valid transaction_id (purchase_without_transaction_id)
        transaction_id IS NOT NULL
        AND TRIM(transaction_id) NOT IN (
            '(not set)',
            '<Other>',
            '(data deleted)',
            ''
        )
        -- Rule 2: Drop purchases with zero or negative revenue (negative_or_zero_revenue)
        AND purchase_revenue_in_usd IS NOT NULL
        AND purchase_revenue_in_usd > 0
    -- Rule 3: Deduplicate repeated purchase events (e.g., thank-you page reload), keeping the earliest hit
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY user_pseudo_id, transaction_id
        ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
    ) = 1
)

SELECT * FROM valid_orders