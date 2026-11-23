{{
    config(
        materialized='table'
    )
}}

WITH date_spine AS (
    SELECT
        d AS full_date
    FROM UNNEST(
        GENERATE_DATE_ARRAY(DATE '2020-11-01', DATE '2021-01-31', INTERVAL 1 DAY)
    ) AS d
),

add_to_cart_days AS (
    SELECT DISTINCT
        event_date
    FROM {{ ref('stg_ga4_events') }}
    WHERE event_name = 'add_to_cart'
),

dim_date_base AS (
    SELECT
        -- 1. Surrogate primary key (YYYYMMDD as INT64)
        CAST(FORMAT_DATE('%Y%m%d', ds.full_date) AS INT64) AS date_key,

        -- 2. STRING calendar attributes
        FORMAT_DATE('%A', ds.full_date) AS day_name,
        FORMAT_DATE('%B', ds.full_date) AS month_name,
        FORMAT_DATE('%Y-%m', ds.full_date) AS year_month,
        CONCAT('Q', CAST(EXTRACT(QUARTER FROM ds.full_date) AS STRING)) AS quarter_name,

        -- 3. INT64 calendar attributes
        EXTRACT(YEAR FROM ds.full_date) AS year,
        EXTRACT(QUARTER FROM ds.full_date) AS quarter,
        EXTRACT(MONTH FROM ds.full_date) AS month,
        EXTRACT(DAY FROM ds.full_date) AS day,
        EXTRACT(DAYOFWEEK FROM ds.full_date) AS day_of_week, -- BigQuery: 1 = Sunday, 7 = Saturday
        EXTRACT(ISOWEEK FROM ds.full_date) AS week_of_year,

        -- 4. BOOL flags
        EXTRACT(DAYOFWEEK FROM ds.full_date) IN (1, 7) AS is_weekend,
        EXTRACT(MONTH FROM ds.full_date) IN (11, 12) AS is_holiday_season, -- Nov-Dec year-end shopping season
        (atc.event_date IS NOT NULL) AS is_add_to_cart_tracked,

        -- 5. DATE attribute
        ds.full_date

    FROM date_spine AS ds
    LEFT JOIN add_to_cart_days AS atc
        ON ds.full_date = atc.event_date
)

SELECT * FROM dim_date_base

UNION ALL

{{ unknown_member(
    sk_col='date_key',
    columns=[
        ('day_name', 'STRING'), ('month_name', 'STRING'), ('year_month', 'STRING'), ('quarter_name', 'STRING'),
        ('year', 'INT64'), ('quarter', 'INT64'), ('month', 'INT64'), ('day', 'INT64'), ('day_of_week', 'INT64'), ('week_of_year', 'INT64'),
        ('is_weekend', 'BOOL'), ('is_holiday_season', 'BOOL'), ('is_add_to_cart_tracked', 'BOOL'),
        ('full_date', 'DATE')
    ]
) }}