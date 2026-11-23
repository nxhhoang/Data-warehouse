WITH distinct_devices AS (
    SELECT DISTINCT
        CASE
            WHEN device_category IN ('<Other>', '(data deleted)', '(not set)', '') OR device_category IS NULL
                THEN 'Unknown'
            ELSE TRIM(device_category)
        END AS device_category,
        CASE
            WHEN operating_system IN ('<Other>', '(data deleted)', '(not set)', '') OR operating_system IS NULL
                THEN 'Unknown'
            ELSE TRIM(operating_system)
        END AS operating_system,
        CASE
            WHEN browser IN ('<Other>', '(data deleted)', '(not set)', '') OR browser IS NULL
                THEN 'Unknown'
            ELSE TRIM(browser)
        END AS browser,
        CASE
            WHEN language IN ('<Other>', '(data deleted)', '(not set)', '') OR language IS NULL
                THEN 'Unknown'
            ELSE TRIM(language)
        END AS language
    FROM {{ ref('stg_ga4_events') }}
),
base AS (
    SELECT
        {{ gen_sk(['device_category', 'operating_system', 'browser', 'language']) }} AS device_key,
        device_category,
        operating_system,
        browser,
        language
    FROM distinct_devices
)
SELECT * FROM base
UNION ALL
{{ unknown_member('device_key', [
    ('device_category', 'STRING'),
    ('operating_system', 'STRING'),
    ('browser', 'STRING'),
    ('language', 'STRING')
]) }}