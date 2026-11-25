-- Grain: Date × Product × Session Source × Device
-- Same measures as fct_product_performance, split by the session's traffic source
-- and device so the dashboard can filter product funnels/sales by channel and
-- device (features 5 and 6). fct_item_events and fct_purchase_items already carry
-- the session-attributed traffic_source_key and the device_key from fct_events.
-- Totals must equal fct_product_performance (tests/assert_product_channel_parity.sql).
WITH item_funnel AS (
    SELECT
        ie.date_key,
        ie.product_key,
        ie.traffic_source_key,
        ie.device_key,
        COUNTIF(ev.event_name = 'view_item') AS item_view_events,
        COUNTIF(ev.event_name = 'select_item') AS item_select_events,
        COUNTIF(ev.event_name = 'add_to_cart') AS item_add_to_cart_events,
        COUNTIF(ev.event_name = 'begin_checkout') AS item_checkout_events,
        SUM(CASE WHEN ev.event_name = 'add_to_cart' THEN ie.quantity ELSE 0 END) AS units_added_to_cart
    FROM {{ ref('fct_item_events') }} ie
    JOIN {{ ref('dim_event') }} ev ON ie.event_key = ev.event_key
    GROUP BY ie.date_key, ie.product_key, ie.traffic_source_key, ie.device_key
),
item_sales AS (
    SELECT
        date_key,
        product_key,
        traffic_source_key,
        device_key,
        SUM(quantity) AS units_sold,
        SUM(item_revenue_usd) AS item_revenue_usd
    FROM {{ ref('fct_purchase_items') }}
    GROUP BY date_key, product_key, traffic_source_key, device_key
)
SELECT
    COALESCE(f.date_key, s.date_key) AS date_key,
    COALESCE(f.product_key, s.product_key) AS product_key,
    COALESCE(f.traffic_source_key, s.traffic_source_key) AS session_source_key,
    COALESCE(f.device_key, s.device_key) AS device_key,
    COALESCE(f.item_view_events, 0) AS item_view_events,
    COALESCE(f.item_select_events, 0) AS item_select_events,
    COALESCE(f.item_add_to_cart_events, 0) AS item_add_to_cart_events,
    COALESCE(f.item_checkout_events, 0) AS item_checkout_events,
    COALESCE(f.units_added_to_cart, 0) AS units_added_to_cart,
    COALESCE(s.units_sold, 0) AS units_sold,
    COALESCE(s.item_revenue_usd, 0.0) AS item_revenue_usd
FROM item_funnel f
FULL OUTER JOIN item_sales s
    ON f.date_key = s.date_key
    AND f.product_key = s.product_key
    AND f.traffic_source_key = s.traffic_source_key
    AND f.device_key = s.device_key
