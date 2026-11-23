{{
    config(
        materialized='view'
    )
}}

WITH product_events AS (
    SELECT
        event_id,
        event_date,
        event_timestamp,
        event_ts,
        event_name,
        user_pseudo_id,
        user_id,
        ga_session_id,
        transaction_id,
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
    WHERE event_name IN (
        'view_item',
        'select_item',
        'add_to_cart',
        'begin_checkout',
        'purchase'
    )
      AND ARRAY_LENGTH(items) > 0
),

unnested_items AS (
    SELECT
        -- 1. Surrogate primary key at (event, item position) grain
        {{ gen_sk(['pe.event_id', 'item_pos']) }} AS event_item_id,

        -- 2. Event & session context keys
        pe.event_id,
        pe.event_date,
        pe.event_timestamp,
        pe.event_ts,
        pe.event_name,
        pe.user_pseudo_id,
        pe.user_id,
        pe.ga_session_id,
        pe.transaction_id,

        -- 3. Traffic, device & geo context (for joining dimensions in item fact tables)
        pe.source,
        pe.medium,
        pe.campaign,
        pe.user_first_source,
        pe.user_first_medium,
        pe.user_first_campaign,
        pe.device_category,
        pe.device_os,
        pe.browser,
        pe.geo_country,
        pe.geo_city,

        -- 4. Item position & core product attributes (for dim_item)
        item_pos,
        it.item_id,
        it.item_name,
        it.item_brand,
        it.item_variant,
        it.item_category,
        it.item_category2,
        it.item_category3,
        it.item_category4,
        it.item_category5,

        -- 5. Item pricing, standardized quantity & revenue metrics
        COALESCE(it.price_in_usd, 0.0) AS price_in_usd,
        COALESCE(it.price, 0.0) AS price,
        COALESCE(it.quantity, 1) AS quantity,
        COALESCE(it.item_revenue_in_usd, 0.0) AS item_revenue_in_usd,
        COALESCE(it.item_revenue, 0.0) AS item_revenue,
        COALESCE(it.item_refund_in_usd, 0.0) AS item_refund_in_usd,

        -- 6. Merchandising & promotion attributes
        it.coupon,
        it.affiliation,
        it.item_list_id,
        it.item_list_name,
        it.item_list_index,
        it.promotion_id,
        it.promotion_name,
        it.creative_name,
        it.creative_slot

    FROM product_events AS pe
    CROSS JOIN UNNEST(pe.items) AS it WITH OFFSET AS item_pos
)

SELECT * FROM unnested_items