{{
    config(
        materialized='table'
    )
}}

WITH distinct_events AS (
    SELECT DISTINCT
        TRIM(event_name) AS event_name
    FROM {{ ref('stg_ga4_events') }}
    WHERE event_name IS NOT NULL
      AND TRIM(event_name) NOT IN ('', '(not set)', '<Other>', '(data deleted)')
),

enriched_events AS (
    SELECT
        event_name,

        -- 1. High-level event category
        CASE
            WHEN event_name IN (
                'view_item_list', 'select_item', 'view_item',
                'add_to_cart', 'remove_from_cart', 'view_cart',
                'begin_checkout', 'add_shipping_info', 'add_payment_info',
                'purchase'
            ) THEN 'Ecommerce'
            WHEN event_name IN ('view_promotion', 'select_promotion') THEN 'Promotion'
            WHEN event_name IN ('first_visit', 'session_start') THEN 'Acquisition & Session'
            WHEN event_name IN ('page_view', 'scroll', 'user_engagement', 'click', 'view_search_results') THEN 'Engagement & Navigation'
            ELSE 'Other'
        END AS event_category,

        -- 2. Marketing & purchase funnel stage label
        CASE
            WHEN event_name IN ('page_view', 'view_item_list', 'select_item') THEN '1. Discovery & Browsing'
            WHEN event_name = 'view_item' THEN '2. Product View'
            WHEN event_name IN ('add_to_cart', 'view_cart') THEN '3. Cart Consideration'
            WHEN event_name IN ('begin_checkout', 'add_shipping_info', 'add_payment_info') THEN '4. Checkout'
            WHEN event_name = 'purchase' THEN '5. Purchase'
            ELSE 'Non-Funnel'
        END AS funnel_stage,

        -- 3. Numeric funnel step order for chronological BI sorting (0 = non-funnel)
        CASE
            WHEN event_name IN ('page_view', 'view_item_list', 'select_item') THEN 1
            WHEN event_name = 'view_item' THEN 2
            WHEN event_name IN ('add_to_cart', 'view_cart') THEN 3
            WHEN event_name IN ('begin_checkout', 'add_shipping_info', 'add_payment_info') THEN 4
            WHEN event_name = 'purchase' THEN 5
            ELSE 0
        END AS funnel_step_order,

        -- 4. Analytical boolean flags
        (event_name = 'purchase') AS is_conversion_event,

        (event_name IN (
            'view_item_list', 'select_item', 'view_item',
            'add_to_cart', 'remove_from_cart', 'view_cart',
            'begin_checkout', 'add_shipping_info', 'add_payment_info',
            'purchase'
        )) AS is_ecommerce_event,

        (event_name IN (
            'page_view', 'scroll', 'user_engagement',
            'click', 'view_search_results'
        )) AS is_engagement_event

    FROM distinct_events
),

dim_event_base AS (
    SELECT
        {{ gen_sk(['event_name']) }} AS event_key,
        event_name,
        event_category,
        funnel_stage,
        funnel_step_order,
        is_conversion_event,
        is_ecommerce_event,
        is_engagement_event
    FROM enriched_events
)

SELECT * FROM dim_event_base

UNION ALL

{{ unknown_member(
    sk_col='event_key',
    columns=[
        ('event_name', 'STRING'),
        ('event_category', 'STRING'),
        ('funnel_stage', 'STRING'),
        ('funnel_step_order', 'INT64'),
        ('is_conversion_event', 'BOOL'),
        ('is_ecommerce_event', 'BOOL'),
        ('is_engagement_event', 'BOOL')
    ]
) }}