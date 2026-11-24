WITH distinct_events AS (
    SELECT DISTINCT TRIM(event_name) AS event_name
    FROM {{ ref('stg_ga4_events') }}
    WHERE event_name IS NOT NULL AND TRIM(event_name) != ''
),
base AS (
    SELECT
        {{ gen_sk(['event_name']) }} AS event_key,
        event_name,
        CASE
            WHEN event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'add_shipping_info', 'add_payment_info', 'purchase')
                THEN 'funnel'
            WHEN event_name IN ('page_view', 'user_engagement', 'scroll', 'session_start', 'first_visit')
                THEN 'engagement'
            WHEN event_name IN ('view_promotion', 'select_promotion', 'select_item', 'view_item_list')
                THEN 'merchandising'
            ELSE 'other'
        END AS event_category,
        CASE event_name
            WHEN 'view_item' THEN 1
            WHEN 'add_to_cart' THEN 2
            WHEN 'begin_checkout' THEN 3
            WHEN 'add_shipping_info' THEN 4
            WHEN 'add_payment_info' THEN 5
            WHEN 'purchase' THEN 6
            ELSE 0
        END AS funnel_step,
        event_name IN ('view_item', 'add_to_cart', 'begin_checkout',
                       'add_shipping_info', 'add_payment_info', 'purchase') AS is_funnel_event,
        event_name = 'purchase' AS is_conversion_event
    FROM distinct_events
)
SELECT * FROM base
UNION ALL
{{ unknown_member('event_key', [
    ('event_name', 'STRING'),
    ('event_category', 'STRING'),
    ('funnel_step', 'INT64'),
    ('is_funnel_event', 'BOOL'),
    ('is_conversion_event', 'BOOL')
]) }}