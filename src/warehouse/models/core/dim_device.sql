{{
    config(
        materialized='table'
    )
}}

WITH normalized_devices AS (
    SELECT DISTINCT
        CASE
            WHEN device_category IS NULL
              OR TRIM(device_category) IN ('', '(not set)', '<Other>', '(data deleted)')
            THEN 'Unknown'
            ELSE LOWER(TRIM(device_category))
        END AS device_category,

        CASE
            WHEN device_os IS NULL
              OR TRIM(device_os) IN ('', '(not set)', '<Other>', '(data deleted)')
            THEN 'Unknown'
            ELSE TRIM(device_os)
        END AS device_os,

        CASE
            WHEN device_os_version IS NULL
              OR TRIM(device_os_version) IN ('', '(not set)', '<Other>', '(data deleted)')
            THEN 'Unknown'
            ELSE TRIM(device_os_version)
        END AS device_os_version,

        CASE
            WHEN device_brand IS NULL
              OR TRIM(device_brand) IN ('', '(not set)', '<Other>', '(data deleted)')
            THEN 'Unknown'
            ELSE TRIM(device_brand)
        END AS device_brand,

        CASE
            WHEN browser IS NULL
              OR TRIM(browser) IN ('', '(not set)', '<Other>', '(data deleted)')
            THEN 'Unknown'
            ELSE TRIM(browser)
        END AS browser

    FROM {{ ref('stg_ga4_events') }}
),

filtered_devices AS (
    SELECT
        device_category,
        device_os,
        device_os_version,
        device_brand,
        browser,
        (device_category IN ('mobile', 'tablet')) AS is_mobile
    FROM normalized_devices
    -- Exclude fully unknown rows so they map cleanly to device_sk = -1
    WHERE NOT (
        device_category = 'Unknown'
        AND device_os = 'Unknown'
        AND device_os_version = 'Unknown'
        AND device_brand = 'Unknown'
        AND browser = 'Unknown'
    )
),

dim_device_base AS (
    SELECT
        {{ gen_sk([
            'device_category',
            'device_os',
            'device_os_version',
            'device_brand',
            'browser'
        ]) }} AS device_sk,
        device_category,
        device_os,
        device_os_version,
        device_brand,
        browser,
        is_mobile
    FROM filtered_devices
)

SELECT * FROM dim_device_base

UNION ALL

{{ unknown_member(
    sk_col='device_sk',
    columns=[
        ('device_category', 'STRING'),
        ('device_os', 'STRING'),
        ('device_os_version', 'STRING'),
        ('device_brand', 'STRING'),
        ('browser', 'STRING'),
        ('is_mobile', 'BOOL')
    ]
) }}