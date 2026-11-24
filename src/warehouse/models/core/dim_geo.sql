WITH distinct_geos AS (
    SELECT DISTINCT
        CASE
            WHEN continent IN ('<Other>', '(data deleted)', '(not set)', '') OR continent IS NULL
                THEN 'Unknown'
            ELSE TRIM(continent)
        END AS continent,
        CASE
            WHEN country IN ('<Other>', '(data deleted)', '(not set)', '') OR country IS NULL
                THEN 'Unknown'
            ELSE TRIM(country)
        END AS country,
        CASE
            WHEN region IN ('<Other>', '(data deleted)', '(not set)', '') OR region IS NULL
                THEN 'Unknown'
            ELSE TRIM(region)
        END AS region,
        CASE
            WHEN city IN ('<Other>', '(data deleted)', '(not set)', '') OR city IS NULL
                THEN 'Unknown'
            ELSE TRIM(city)
        END AS city
    FROM {{ ref('stg_ga4_events') }}
),
base AS (
    SELECT
        {{ gen_sk(['continent', 'country', 'region', 'city']) }} AS geo_key,
        continent,
        country,
        region,
        city
    FROM distinct_geos
)
SELECT * FROM base
UNION ALL
{{ unknown_member('geo_key', [
    ('continent', 'STRING'),
    ('country', 'STRING'),
    ('region', 'STRING'),
    ('city', 'STRING')
]) }}