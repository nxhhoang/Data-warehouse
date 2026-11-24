WITH date_spine AS (
    SELECT d AS full_date
    FROM UNNEST(GENERATE_DATE_ARRAY(
        PARSE_DATE('%Y%m%d', '{{ var("start_date") }}'),
        PARSE_DATE('%Y%m%d', '{{ var("end_date") }}')
    )) AS d
),
tracked_days AS (
    SELECT
        event_date,
        COUNTIF(event_name = 'add_to_cart') > 0 AS is_add_to_cart_tracked
    FROM {{ ref('stg_ga4_events') }}
    GROUP BY event_date
),
base AS (
    SELECT
        CAST(FORMAT_DATE('%Y%m%d', ds.full_date) AS INT64) AS date_key,
        ds.full_date,
        EXTRACT(DAYOFWEEK FROM ds.full_date) AS day_of_week,
        FORMAT_DATE('%A', ds.full_date) AS day_name,
        EXTRACT(ISOWEEK FROM ds.full_date) AS week_of_year,
        EXTRACT(MONTH FROM ds.full_date) AS month,
        EXTRACT(YEAR FROM ds.full_date) AS year,
        FORMAT_DATE('%Y-%m', ds.full_date) AS year_month,
        EXTRACT(QUARTER FROM ds.full_date) AS quarter,
        EXTRACT(DAYOFWEEK FROM ds.full_date) IN (1, 7) AS is_weekend,
        -- Peak year-end shopping season (Black Friday -> end of December)
        ds.full_date BETWEEN DATE('2020-11-25') AND DATE('2020-12-31') AS is_holiday_season,
        COALESCE(td.is_add_to_cart_tracked, FALSE) AS is_add_to_cart_tracked
    FROM date_spine ds
    LEFT JOIN tracked_days td ON ds.full_date = td.event_date
)
SELECT * FROM base
UNION ALL
{{ unknown_member('date_key', [
    ('full_date', 'DATE'),
    ('day_of_week', 'INT64'),
    ('day_name', 'STRING'),
    ('week_of_year', 'INT64'),
    ('month', 'INT64'),
    ('year', 'INT64'),
    ('year_month', 'STRING'),
    ('quarter', 'INT64'),
    ('is_weekend', 'BOOL'),
    ('is_holiday_season', 'BOOL'),
    ('is_add_to_cart_tracked', 'BOOL')
]) }}