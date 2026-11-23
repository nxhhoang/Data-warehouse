-- dim_product.sql
{{
    config(
        materialized='table'
    )
}}

WITH clean_items AS (
    SELECT
        TRIM(item_id) AS item_id,
        NULLIF(TRIM(item_name), '') AS item_name,
        NULLIF(TRIM(item_brand), '') AS item_brand,
        NULLIF(TRIM(item_category), '') AS item_category,
        NULLIF(TRIM(item_category2), '') AS item_category2,
        NULLIF(TRIM(item_category3), '') AS item_category3
    FROM {{ ref('stg_ga4_items') }}
    WHERE item_id IS NOT NULL
      AND TRIM(item_id) NOT IN ('', '(not set)', '<Other>', '(data deleted)')
),

deduplicated_products AS (
    SELECT
        item_id,
        COALESCE(
            APPROX_TOP_COUNT(
                IF(item_name IN ('(not set)', '<Other>', '(data deleted)'), NULL, item_name), 1
            )[SAFE_OFFSET(0)].value,
            'Unknown'
        ) AS item_name,
        COALESCE(
            APPROX_TOP_COUNT(
                IF(item_brand IN ('(not set)', '<Other>', '(data deleted)'), NULL, item_brand), 1
            )[SAFE_OFFSET(0)].value,
            'Unknown'
        ) AS item_brand,
        COALESCE(
            APPROX_TOP_COUNT(
                IF(item_category IN ('(not set)', '<Other>', '(data deleted)'), NULL, item_category), 1
            )[SAFE_OFFSET(0)].value,
            'Unknown'
        ) AS item_category,
        COALESCE(
            APPROX_TOP_COUNT(
                IF(item_category2 IN ('(not set)', '<Other>', '(data deleted)'), NULL, item_category2), 1
            )[SAFE_OFFSET(0)].value,
            'Unknown'
        ) AS item_category2,
        COALESCE(
            APPROX_TOP_COUNT(
                IF(item_category3 IN ('(not set)', '<Other>', '(data deleted)'), NULL, item_category3), 1
            )[SAFE_OFFSET(0)].value,
            'Unknown'
        ) AS item_category3
    FROM clean_items
    GROUP BY item_id
),

dim_product_base AS (
    SELECT
        {{ gen_sk(['item_id']) }} AS product_sk,
        item_id,
        item_name,
        item_brand,
        item_category,
        item_category2,
        item_category3
    FROM deduplicated_products
)

SELECT * FROM dim_product_base

UNION ALL

{{ unknown_member(
    sk_col='product_sk',
    columns=[
        ('item_id', 'STRING'),
        ('item_name', 'STRING'),
        ('item_brand', 'STRING'),
        ('item_category', 'STRING'),
        ('item_category2', 'STRING'),
        ('item_category3', 'STRING')
    ]
) }}