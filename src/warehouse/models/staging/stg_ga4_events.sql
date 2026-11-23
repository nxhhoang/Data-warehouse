{{
    config(
        materialized='view'
    )
}}

WITH source_events AS (
    {% if var('use_sample_data', true) %}
        SELECT *
        FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
    {% else %}
        SELECT *
        FROM {{ source('raw_ga4', 'events') }}
    {% endif %}
),

staged_events AS (
    SELECT
        -- 1. Event surrogate key (aligned with duplicate_check.event_key_fields)
        {{ gen_sk([
            'user_pseudo_id',
            'event_timestamp',
            'event_name',
            'event_bundle_sequence_id'
        ]) }} AS event_id,

        -- 2. Core event metadata & timestamps
        PARSE_DATE('%Y%m%d', event_date) AS event_date,
        event_timestamp,
        TIMESTAMP_MICROS(event_timestamp) AS event_ts,
        event_name,
        event_bundle_sequence_id,
        COALESCE(event_value_in_usd, 0.0) AS event_value_in_usd,

        -- 3. User identifiers
        user_pseudo_id,
        user_id,
        user_first_touch_timestamp,

        -- 4. Extract 9 parameters from event_params via scalar subqueries
        (
            SELECT value.int_value
            FROM UNNEST(event_params)
            WHERE key = 'ga_session_id'
        ) AS ga_session_id,

        (
            SELECT value.int_value
            FROM UNNEST(event_params)
            WHERE key = 'engaged_session_event'
        ) AS engaged_session_event,

        (
            SELECT COALESCE(CAST(value.int_value AS STRING), value.string_value)
            FROM UNNEST(event_params)
            WHERE key = 'session_engaged'
        ) AS session_engaged,

        (
            SELECT value.int_value
            FROM UNNEST(event_params)
            WHERE key = 'engagement_time_msec'
        ) AS engagement_time_msec,

        (
            SELECT value.string_value
            FROM UNNEST(event_params)
            WHERE key = 'page_location'
        ) AS page_location,

        (
            SELECT value.string_value
            FROM UNNEST(event_params)
            WHERE key = 'page_title'
        ) AS page_title,

        (
            SELECT value.string_value
            FROM UNNEST(event_params)
            WHERE key = 'source'
        ) AS source,

        (
            SELECT value.string_value
            FROM UNNEST(event_params)
            WHERE key = 'medium'
        ) AS medium,

        (
            SELECT value.string_value
            FROM UNNEST(event_params)
            WHERE key = 'campaign'
        ) AS campaign,

        -- 5. Device attributes (for dim_device)
        device.category AS device_category,
        device.operating_system AS device_os,
        device.operating_system_version AS device_os_version,
        device.mobile_brand_name AS device_brand,
        device.web_info.browser AS browser,

        -- 6. Geographic attributes (for dim_geo)
        geo.continent AS geo_continent,
        geo.country AS geo_country,
        geo.region AS geo_region,
        geo.city AS geo_city,

        -- 7. User-level / First-touch traffic source (fallback when event_params lacks UTM tags)
        traffic_source.source AS user_first_source,
        traffic_source.medium AS user_first_medium,
        traffic_source.name AS user_first_campaign,

        -- 8. Ecommerce transaction metrics & items array (for fct_purchase_items / fct_item_events)
        ecommerce.transaction_id AS transaction_id,
        ecommerce.purchase_revenue_in_usd AS purchase_revenue_in_usd,
        ecommerce.total_item_quantity AS total_item_quantity,
        items

    FROM source_events
    WHERE user_pseudo_id IS NOT NULL
      AND event_timestamp IS NOT NULL
      AND event_name IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY event_id
        ORDER BY event_timestamp ASC
    ) = 1
)

SELECT * FROM staged_events