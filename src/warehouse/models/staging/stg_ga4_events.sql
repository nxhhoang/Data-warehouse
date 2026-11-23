WITH raw_events AS (
    SELECT
        event_date,
        event_timestamp,
        event_name,
        event_bundle_sequence_id,
        user_pseudo_id,
        user_first_touch_timestamp,
        traffic_source.source AS user_raw_source,
        traffic_source.medium AS user_raw_medium,
        traffic_source.name AS user_raw_campaign,
        device.category AS device_category,
        device.operating_system AS operating_system,
        device.web_info.browser AS browser,
        device.language AS language,
        geo.continent AS continent,
        geo.country AS country,
        geo.region AS region,
        geo.city AS city,
        ecommerce.transaction_id AS transaction_id,
        ecommerce.purchase_revenue_in_usd AS purchase_revenue_in_usd,
        ecommerce.total_item_quantity AS total_item_quantity,
        items,

        -- Extract event_params using scalar subqueries to avoid duplicating event rows
        (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id' LIMIT 1) AS ga_session_id,
        (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_number' LIMIT 1) AS ga_session_number,
        (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'engaged_session_event' LIMIT 1) AS engaged_session_event,
        (SELECT COALESCE(CAST(value.int_value AS STRING), value.string_value)
         FROM UNNEST(event_params) WHERE key = 'session_engaged' LIMIT 1) AS session_engaged,
        COALESCE(
            (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'engagement_time_msec' LIMIT 1),
            0
        ) AS engagement_time_msec,
        (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location' LIMIT 1) AS page_location,
        (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_title' LIMIT 1) AS page_title,
        (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'source' LIMIT 1) AS ep_source,
        (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'medium' LIMIT 1) AS ep_medium,
        (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'campaign' LIMIT 1) AS ep_campaign
    FROM {{ source('ga4_raw', 'events') }}
    WHERE _TABLE_SUFFIX BETWEEN '{{ var("start_date") }}' AND '{{ var("end_date") }}'
),
enriched AS (
    SELECT
        {{ gen_sk(['user_pseudo_id', 'event_timestamp', 'event_name', 'event_bundle_sequence_id']) }} AS event_id,
        PARSE_DATE('%Y%m%d', event_date) AS event_date,
        CAST(event_date AS INT64) AS date_key,
        event_timestamp,
        TIMESTAMP_MICROS(event_timestamp) AS event_ts_utc,
        event_name,
        event_bundle_sequence_id,
        user_pseudo_id,
        user_first_touch_timestamp,
        ga_session_id,
        CASE
            WHEN user_pseudo_id IS NOT NULL AND ga_session_id IS NOT NULL
                THEN CONCAT(user_pseudo_id, '_', CAST(ga_session_id AS STRING))
            ELSE NULL
        END AS session_id,
        ga_session_number,
        engaged_session_event,
        session_engaged,
        engagement_time_msec,
        page_location,
        page_title,
        ep_source,
        ep_medium,
        ep_campaign,
        user_raw_source,
        user_raw_medium,
        user_raw_campaign,
        device_category,
        operating_system,
        browser,
        language,
        continent,
        country,
        region,
        city,
        NULLIF(TRIM(transaction_id), '') AS transaction_id,
        purchase_revenue_in_usd,
        total_item_quantity,
        items
    FROM raw_events
)
SELECT *
FROM enriched
-- Deduplicate events by event_id (config/quality_rules.yaml)
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY event_id
    ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
) = 1