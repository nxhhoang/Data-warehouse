{{
    config(
        materialized='table',
        partition_by={
            "field": "event_date",
            "data_type": "date",
            "granularity": "day"
        },
        cluster_by=["event_key", "product_sk"]
    )
}}

WITH funnel_item_events AS (
    SELECT
        event_id,
        event_date,
        event_ts,
        event_timestamp,
        event_name,
        item_pos,
        item_id,
        item_variant,
        price_in_usd,
        quantity,
        item_list_id,
        item_list_name,
        item_list_index,
        promotion_id,
        promotion_name,
        creative_name,
        creative_slot
    FROM {{ ref('stg_ga4_items') }}
    WHERE event_name IN (
        'view_item',
        'select_item',
        'add_to_cart',
        'begin_checkout'
    )
),

event_context AS (
    SELECT
        event_id,
        date_key,
        event_key,
        user_sk,
        traffic_source_key,
        device_sk,
        geo_sk,
        page_sk,
        session_id
    FROM {{ ref('fct_events') }}
)

SELECT
    -- 1. Primary Key (1 row = 1 pre-purchase product interaction)
    {{ gen_sk(['ie.event_id', 'ie.item_pos']) }} AS item_event_id,

    -- 2. Foreign Keys to Conformed Dimensions (guaranteed non-null via -1 fallback)
    COALESCE(ec.date_key, CAST(FORMAT_DATE('%Y%m%d', ie.event_date) AS INT64), -1) AS date_key,
    COALESCE(ec.event_key, -1) AS event_key,

    CASE
        WHEN ie.item_id IS NULL
          OR TRIM(ie.item_id) IN ('', '(not set)', '<Other>', '(data deleted)')
        THEN -1
        ELSE {{ gen_sk(['TRIM(ie.item_id)']) }}
    END AS product_sk,

    COALESCE(ec.user_sk, -1) AS user_sk,
    COALESCE(ec.traffic_source_key, -1) AS traffic_source_key,
    COALESCE(ec.device_sk, -1) AS device_sk,
    COALESCE(ec.geo_sk, -1) AS geo_sk,
    COALESCE(ec.page_sk, -1) AS page_sk,

    -- 3. Event, Session & Merchandising Degenerate Dimensions
    ie.event_id,
    COALESCE(ec.session_id, -1) AS session_id,
    ie.event_date,
    ie.event_ts,
    ie.event_timestamp,
    ie.item_pos,
    COALESCE(NULLIF(TRIM(ie.item_variant), ''), 'Unknown') AS item_variant,
    COALESCE(NULLIF(TRIM(ie.item_list_id), ''), 'Unknown') AS item_list_id,
    COALESCE(NULLIF(TRIM(ie.item_list_name), ''), 'Unknown') AS item_list_name,
    COALESCE(NULLIF(TRIM(ie.item_list_index), ''), 'Unknown') AS item_list_index,
    COALESCE(NULLIF(TRIM(ie.promotion_id), ''), 'Unknown') AS promotion_id,
    COALESCE(NULLIF(TRIM(ie.promotion_name), ''), 'Unknown') AS promotion_name,
    COALESCE(NULLIF(TRIM(ie.creative_name), ''), 'Unknown') AS creative_name,
    COALESCE(NULLIF(TRIM(ie.creative_slot), ''), 'Unknown') AS creative_slot,

    -- 4. Additive Item Interaction Measures
    CAST(ie.quantity AS INT64) AS quantity,
    ie.price_in_usd

FROM funnel_item_events AS ie
LEFT JOIN event_context AS ec
    ON ie.event_id = ec.event_id