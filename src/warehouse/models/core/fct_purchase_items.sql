{{
    config(
        materialized='table',
        partition_by={
            "field": "event_date",
            "data_type": "date",
            "granularity": "day"
        },
        cluster_by=["product_sk", "traffic_source_key"]
    )
}}

WITH purchase_items AS (
    SELECT
        event_item_id,
        event_id,
        event_date,
        event_ts,
        event_timestamp,
        item_pos,
        item_id,
        item_variant,
        price_in_usd,
        quantity,
        item_revenue_in_usd,
        item_refund_in_usd,
        coupon,
        affiliation,
        item_list_id,
        item_list_name,
        item_list_index,
        promotion_id,
        promotion_name,
        creative_name,
        creative_slot
    FROM {{ ref('stg_ga4_items') }}
    WHERE event_name = 'purchase'
),

valid_orders AS (
    SELECT
        event_id,
        order_sk,
        transaction_id
    FROM {{ ref('stg_valid_orders') }}
),

event_context AS (
    SELECT
        event_id,
        date_key,
        user_sk,
        traffic_source_key,
        device_sk,
        geo_sk,
        page_sk,
        session_id
    FROM {{ ref('fct_events') }}
)

SELECT
    -- 1. Primary Key (1 row = 1 line item in a validated order)
    pi.event_item_id,

    -- 2. Foreign Keys to Conformed Dimensions (guaranteed non-null via -1 fallback)
    COALESCE(ec.date_key, CAST(FORMAT_DATE('%Y%m%d', pi.event_date) AS INT64), -1) AS date_key,

    CASE
        WHEN pi.item_id IS NULL
          OR TRIM(pi.item_id) IN ('', '(not set)', '<Other>', '(data deleted)')
        THEN -1
        ELSE {{ gen_sk(['TRIM(pi.item_id)']) }}
    END AS product_sk,

    COALESCE(ec.user_sk, -1) AS user_sk,
    COALESCE(ec.traffic_source_key, -1) AS traffic_source_key,
    COALESCE(ec.device_sk, -1) AS device_sk,
    COALESCE(ec.geo_sk, -1) AS geo_sk,
    COALESCE(ec.page_sk, -1) AS page_sk,

    -- 3. Order, Session & Degenerate Dimensions
    vo.order_sk,
    pi.event_id,
    COALESCE(ec.session_id, -1) AS session_id,
    vo.transaction_id,
    pi.event_date,
    pi.event_ts,
    pi.event_timestamp,
    pi.item_pos,
    COALESCE(NULLIF(TRIM(pi.item_variant), ''), 'Unknown') AS item_variant,
    COALESCE(NULLIF(TRIM(pi.coupon), ''), 'Unknown') AS coupon,
    COALESCE(NULLIF(TRIM(pi.affiliation), ''), 'Unknown') AS affiliation,
    COALESCE(NULLIF(TRIM(pi.item_list_name), ''), 'Unknown') AS item_list_name,
    COALESCE(NULLIF(TRIM(pi.promotion_name), ''), 'Unknown') AS promotion_name,

    -- 4. Additive Line-Item Measures
    CAST(pi.quantity AS INT64) AS quantity,
    pi.price_in_usd,

    CASE
        WHEN pi.item_revenue_in_usd > 0 THEN pi.item_revenue_in_usd
        ELSE pi.price_in_usd * pi.quantity
    END AS item_revenue_in_usd,

    pi.item_refund_in_usd,

    (
        CASE
            WHEN pi.item_revenue_in_usd > 0 THEN pi.item_revenue_in_usd
            ELSE pi.price_in_usd * pi.quantity
        END - pi.item_refund_in_usd
    ) AS net_item_revenue_in_usd

FROM purchase_items AS pi
INNER JOIN valid_orders AS vo
    ON pi.event_id = vo.event_id
LEFT JOIN event_context AS ec
    ON pi.event_id = ec.event_id