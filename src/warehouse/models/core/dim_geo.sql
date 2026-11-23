{{
    config(
        materialized='table'
    )
}}

WITH normalized_geos AS (
    SELECT DISTINCT
        CASE
            WHEN geo_continent IS NULL
              OR TRIM(geo_continent) IN ('', '(not set)', '<Other>', '(data deleted)')
            THEN 'Unknown'
            ELSE TRIM(geo_continent)
        END AS geo_continent,

        CASE
            WHEN geo_country IS NULL
              OR TRIM(geo_country) IN ('', '(not set)', '<Other>', '(data deleted)')
            THEN 'Unknown'
            ELSE TRIM(geo_country)
        END AS geo_country,

        CASE
            WHEN geo_region IS NULL
              OR TRIM(geo_region) IN ('', '(not set)', '<Other>', '(data deleted)')
            THEN 'Unknown'
            ELSE TRIM(geo_region)
        END AS geo_region,

        CASE
            WHEN geo_city IS NULL
              OR TRIM(geo_city) IN ('', '(not set)', '<Other>', '(data deleted)')
            THEN 'Unknown'
            ELSE TRIM(geo_city)
        END AS geo_city

    FROM {{ ref('stg_ga4_events') }}
),

filtered_geos AS (
    SELECT
        geo_continent,
        geo_country,
        geo_region,
        geo_city
    FROM normalized_geos
    -- Exclude fully unknown rows so they map cleanly to geo_sk = -1
    WHERE NOT (
        geo_continent = 'Unknown'
        AND geo_country = 'Unknown'
        AND geo_region = 'Unknown'
        AND geo_city = 'Unknown'
    )
),

dim_geo_base AS (
    SELECT
        {{ gen_sk([
            'geo_continent',
            'geo_country',
            'geo_region',
            'geo_city'
        ]) }} AS geo_sk,
        geo_continent,
        geo_country,
        geo_region,
        geo_city
    FROM filtered_geos
)

SELECT * FROM dim_geo_base

UNION ALL

{{ unknown_member(
    sk_col='geo_sk',
    columns=[
        ('geo_continent', 'STRING'),
        ('geo_country', 'STRING'),
        ('geo_region', 'STRING'),
        ('geo_city', 'STRING')
    ]
) }}