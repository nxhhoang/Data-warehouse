WITH events_with_keys AS (
    SELECT
        e.session_id,
        e.user_pseudo_id,
        e.event_date,
        e.date_key,
        e.event_timestamp,
        e.event_ts_utc,
        e.event_bundle_sequence_id,
        e.event_name,
        e.ga_session_number,
        e.engaged_session_event,
        e.session_engaged,
        e.engagement_time_msec,
        COALESCE(u.user_key, -1) AS user_key,
        COALESCE(u.user_traffic_source_key, -1) AS user_source_key,
        COALESCE(dev.device_key, -1) AS device_key,
        COALESCE(geo.geo_key, -1) AS geo_key,
        COALESCE(pg.page_key, -1) AS page_key,
        -- Event-level source key (NULL if the event has no source/medium parameters)
        CASE
            WHEN e.ep_source IS NOT NULL OR e.ep_medium IS NOT NULL OR e.ep_campaign IS NOT NULL
                THEN {{ gen_sk([
                    "CASE WHEN e.ep_source IN ('<Other>', '(data deleted)', '(not set)', '') OR e.ep_source IS NULL THEN 'Unknown' ELSE TRIM(e.ep_source) END",
                    "CASE WHEN e.ep_medium IN ('<Other>', '(data deleted)', '(not set)', '') OR e.ep_medium IS NULL THEN 'Unknown' ELSE TRIM(e.ep_medium) END",
                    "CASE WHEN e.ep_campaign IN ('<Other>', '(data deleted)', '(not set)', '') OR e.ep_campaign IS NULL THEN 'Unknown' ELSE TRIM(e.ep_campaign) END"
                ]) }}
            ELSE NULL
        END AS event_source_key
    FROM {{ ref('stg_ga4_events') }} e
    LEFT JOIN {{ ref('dim_user') }} u
        ON e.user_pseudo_id = u.user_pseudo_id
    LEFT JOIN {{ ref('dim_device') }} dev
        ON {{ gen_sk([
            "CASE WHEN e.device_category IN ('<Other>', '(data deleted)', '(not set)', '') OR e.device_category IS NULL THEN 'Unknown' ELSE TRIM(e.device_category) END",
            "CASE WHEN e.operating_system IN ('<Other>', '(data deleted)', '(not set)', '') OR e.operating_system IS NULL THEN 'Unknown' ELSE TRIM(e.operating_system) END",
            "CASE WHEN e.browser IN ('<Other>', '(data deleted)', '(not set)', '') OR e.browser IS NULL THEN 'Unknown' ELSE TRIM(e.browser) END",
            "CASE WHEN e.language IN ('<Other>', '(data deleted)', '(not set)', '') OR e.language IS NULL THEN 'Unknown' ELSE TRIM(e.language) END"
        ]) }} = dev.device_key
    LEFT JOIN {{ ref('dim_geo') }} geo
        ON {{ gen_sk([
            "CASE WHEN e.continent IN ('<Other>', '(data deleted)', '(not set)', '') OR e.continent IS NULL THEN 'Unknown' ELSE TRIM(e.continent) END",
            "CASE WHEN e.country IN ('<Other>', '(data deleted)', '(not set)', '') OR e.country IS NULL THEN 'Unknown' ELSE TRIM(e.country) END",
            "CASE WHEN e.region IN ('<Other>', '(data deleted)', '(not set)', '') OR e.region IS NULL THEN 'Unknown' ELSE TRIM(e.region) END",
            "CASE WHEN e.city IN ('<Other>', '(data deleted)', '(not set)', '') OR e.city IS NULL THEN 'Unknown' ELSE TRIM(e.city) END"
        ]) }} = geo.geo_key
    LEFT JOIN {{ ref('dim_page') }} pg
        ON {{ gen_sk(["REGEXP_REPLACE(TRIM(e.page_location), r'[?#].*$', '')"]) }} = pg.page_key
    WHERE e.session_id IS NOT NULL
),
session_first_attrs AS (
    SELECT
        session_id,
        -- Cross-midnight session rule (0.23%): take the date of the first event in the session
        FIRST_VALUE(date_key) OVER w_asc AS date_key,
        FIRST_VALUE(event_ts_utc) OVER w_asc AS session_start_ts,
        FIRST_VALUE(user_key) OVER w_asc AS user_key,
        FIRST_VALUE(user_source_key) OVER w_asc AS user_source_key,
        FIRST_VALUE(device_key) OVER w_asc AS device_key,
        FIRST_VALUE(geo_key) OVER w_asc AS geo_key,
        FIRST_VALUE(page_key) OVER w_asc AS landing_page_key,
        FIRST_VALUE(event_source_key IGNORE NULLS) OVER (
            PARTITION BY session_id
            ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS first_session_source_key
    FROM events_with_keys
    -- BigQuery clause order: QUALIFY must come before WINDOW
    QUALIFY ROW_NUMBER() OVER w_asc = 1
    WINDOW w_asc AS (
        PARTITION BY session_id
        ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
    )
),
session_metrics AS (
    SELECT
        session_id,
        COUNT(*) AS event_count,
        COUNTIF(event_name = 'page_view') AS page_view_count,
        COUNTIF(event_name = 'view_item') AS view_item_count,
        SUM(engagement_time_msec) AS engagement_time_msec,
        MAX(CASE WHEN session_engaged = '1' OR engaged_session_event = 1 THEN 1 ELSE 0 END) AS is_engaged,
        -- New-user session = the session holding the user's first_visit (same rule as
        -- the new_user_rate KPI); every later session of that user counts as returning
        MAX(CASE WHEN event_name = 'first_visit' THEN 1 ELSE 0 END) AS is_new_user_session,
        -- GA4's own per-user session counter (survey 07: present on 100% of events);
        -- unlike a ROW_NUMBER over our window it also counts sessions before 2020-11-01
        MAX(ga_session_number) AS user_session_number,
        MAX(CASE WHEN event_name = 'view_item' THEN 1 ELSE 0 END) AS has_view_item,
        MAX(CASE WHEN event_name = 'add_to_cart' THEN 1 ELSE 0 END) AS has_add_to_cart,
        MAX(CASE WHEN event_name = 'begin_checkout' THEN 1 ELSE 0 END) AS has_begin_checkout,
        MAX(CASE WHEN event_name = 'add_shipping_info' THEN 1 ELSE 0 END) AS has_add_shipping_info,
        MAX(CASE WHEN event_name = 'add_payment_info' THEN 1 ELSE 0 END) AS has_add_payment_info
    FROM events_with_keys
    GROUP BY session_id
),
session_orders AS (
    SELECT
        session_id,
        COUNT(DISTINCT transaction_id) AS order_count,
        SUM(revenue_usd) AS revenue_usd
    FROM {{ ref('stg_valid_orders') }}
    WHERE session_id IS NOT NULL
    GROUP BY session_id
)
SELECT
    fa.session_id, -- STRING
    COALESCE(fa.date_key, -1) AS date_key, -- INT64
    COALESCE(fa.user_key, -1) AS user_key, -- INT64
    COALESCE(fa.device_key, -1) AS device_key, -- INT64
    COALESCE(fa.geo_key, -1) AS geo_key, -- INT64
    COALESCE(fa.landing_page_key, -1) AS landing_page_key, -- INT64
    -- 2-tier source attribution: prioritize session-level source, otherwise fallback to user-level source
    COALESCE(fa.first_session_source_key, fa.user_source_key, -1) AS session_source_key, -- INT64
    COALESCE(fa.user_source_key, -1) AS user_source_key, -- INT64
    CASE
        WHEN fa.first_session_source_key IS NOT NULL THEN 'session'
        ELSE 'user_fallback'
    END AS attribution_basis, -- STRING: session or user_fallback
    fa.session_start_ts, -- TIMESTAMP
    sm.is_new_user_session, -- INT64: 0 or 1
    COALESCE(sm.user_session_number, -1) AS user_session_number, -- INT64
    sm.event_count, -- INT64
    sm.page_view_count, -- INT64
    sm.view_item_count, -- INT64
    sm.engagement_time_msec, -- INT64: milliseconds
    sm.is_engaged, -- INT64: 0 or 1
    sm.has_view_item, -- INT64: 0 or 1
    sm.has_add_to_cart, -- INT64: 0 or 1
    sm.has_begin_checkout, -- INT64: 0 or 1
    sm.has_add_shipping_info, -- INT64: 0 or 1
    sm.has_add_payment_info, -- INT64: 0 or 1
    CASE WHEN COALESCE(so.order_count, 0) > 0 THEN 1 ELSE 0 END AS has_purchase, -- INT64: 0 or 1
    COALESCE(so.order_count, 0) AS order_count, -- INT64
    COALESCE(so.revenue_usd, 0.0) AS revenue_usd -- FLOAT64: US dollars
FROM session_first_attrs fa
JOIN session_metrics sm ON fa.session_id = sm.session_id
LEFT JOIN session_orders so ON fa.session_id = so.session_id