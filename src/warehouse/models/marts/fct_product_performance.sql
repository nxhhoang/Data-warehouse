-- Grain: Date × Product
WITH item_funnel AS (
    SELECT
        ie.date_key,
        ie.product_key,
        COUNTIF(ev.event_name = 'view_item') AS item_view_events,
        COUNTIF(ev.event_name = 'select_item') AS item_select_events,
        COUNTIF(ev.event_name = 'add_to_cart') AS item_add_to_cart_events,
        COUNTIF(ev.event_name = 'begin_checkout') AS item_checkout_events,
        SUM(CASE WHEN ev.event_name = 'add_to_cart' THEN ie.quantity ELSE 0 END) AS units_added_to_cart
    FROM {{ ref('fct_item_events') }} ie
    JOIN {{ ref('dim_event') }} ev ON ie.event_key = ev.event_key
    GROUP BY ie.date_key, ie.product_key
),
item_sales AS (
    SELECT
        date_key,
        product_key,
        SUM(quantity) AS units_sold,
        SUM(item_revenue_usd) AS item_revenue_usd
    FROM {{ ref('fct_purchase_items') }}
    GROUP BY date_key, product_key
)
SELECT
    COALESCE(f.date_key, s.date_key) AS date_key, -- INT64
    COALESCE(f.product_key, s.product_key) AS product_key, -- INT64
    COALESCE(f.item_view_events, 0) AS item_view_events, -- INT64
    COALESCE(f.item_select_events, 0) AS item_select_events, -- INT64
    COALESCE(f.item_add_to_cart_events, 0) AS item_add_to_cart_events, -- INT64
    COALESCE(f.item_checkout_events, 0) AS item_checkout_events, -- INT64
    COALESCE(f.units_added_to_cart, 0) AS units_added_to_cart, -- INT64
    COALESCE(s.units_sold, 0) AS units_sold, -- INT64
    COALESCE(s.item_revenue_usd, 0.0) AS item_revenue_usd -- FLOAT64: US dollars
FROM item_funnel f
FULL OUTER JOIN item_sales s
    ON f.date_key = s.date_key AND f.product_key = s.product_key