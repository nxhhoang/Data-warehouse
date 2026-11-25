-- fct_product_channel_daily only adds the source and device keys to the grain of
-- fct_product_performance, so every measure must sum to the same total in both
-- marts. Any returned row is a measure whose totals differ.
WITH by_channel AS (
    SELECT
        SUM(item_view_events) AS item_view_events,
        SUM(item_select_events) AS item_select_events,
        SUM(item_add_to_cart_events) AS item_add_to_cart_events,
        SUM(item_checkout_events) AS item_checkout_events,
        SUM(units_added_to_cart) AS units_added_to_cart,
        SUM(units_sold) AS units_sold,
        ROUND(SUM(item_revenue_usd), 2) AS item_revenue_usd
    FROM {{ ref('fct_product_channel_daily') }}
),
by_product AS (
    SELECT
        SUM(item_view_events) AS item_view_events,
        SUM(item_select_events) AS item_select_events,
        SUM(item_add_to_cart_events) AS item_add_to_cart_events,
        SUM(item_checkout_events) AS item_checkout_events,
        SUM(units_added_to_cart) AS units_added_to_cart,
        SUM(units_sold) AS units_sold,
        ROUND(SUM(item_revenue_usd), 2) AS item_revenue_usd
    FROM {{ ref('fct_product_performance') }}
),
compared AS (
    SELECT 'item_view_events' AS measure, c.item_view_events AS channel_total, p.item_view_events AS product_total FROM by_channel c CROSS JOIN by_product p
    UNION ALL
    SELECT 'item_select_events', c.item_select_events, p.item_select_events FROM by_channel c CROSS JOIN by_product p
    UNION ALL
    SELECT 'item_add_to_cart_events', c.item_add_to_cart_events, p.item_add_to_cart_events FROM by_channel c CROSS JOIN by_product p
    UNION ALL
    SELECT 'item_checkout_events', c.item_checkout_events, p.item_checkout_events FROM by_channel c CROSS JOIN by_product p
    UNION ALL
    SELECT 'units_added_to_cart', c.units_added_to_cart, p.units_added_to_cart FROM by_channel c CROSS JOIN by_product p
    UNION ALL
    SELECT 'units_sold', c.units_sold, p.units_sold FROM by_channel c CROSS JOIN by_product p
    UNION ALL
    SELECT 'item_revenue_usd', c.item_revenue_usd, p.item_revenue_usd FROM by_channel c CROSS JOIN by_product p
)
SELECT *
FROM compared
WHERE ABS(COALESCE(channel_total, 0) - COALESCE(product_total, 0)) > 0.01
