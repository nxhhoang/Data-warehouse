WITH valid_items AS (
    SELECT
        TRIM(item_id) AS item_id,
        NULLIF(item_name, '(not set)') AS item_name,
        NULLIF(item_brand, '(not set)') AS item_brand,
        NULLIF(item_category, '(not set)') AS item_category,
        NULLIF(item_category2, '(not set)') AS item_category2,
        NULLIF(item_category3, '(not set)') AS item_category3
    FROM {{ ref('stg_ga4_items') }}
    WHERE item_id IS NOT NULL AND TRIM(item_id) NOT IN ('', '(not set)', '<Other>')
),
base AS (
    SELECT
        {{ gen_sk(['item_id']) }} AS product_key,
        item_id,
        -- Survey 08: retrieve the most frequent attribute per item_id
        COALESCE(APPROX_TOP_COUNT(item_name, 1)[OFFSET(0)].value, 'Unknown') AS item_name,
        COALESCE(APPROX_TOP_COUNT(item_brand, 1)[OFFSET(0)].value, 'Unknown') AS item_brand,
        COALESCE(APPROX_TOP_COUNT(item_category, 1)[OFFSET(0)].value, 'Unknown') AS item_category,
        COALESCE(APPROX_TOP_COUNT(item_category2, 1)[OFFSET(0)].value, 'Unknown') AS item_category2,
        COALESCE(APPROX_TOP_COUNT(item_category3, 1)[OFFSET(0)].value, 'Unknown') AS item_category3
    FROM valid_items
    GROUP BY item_id
)
SELECT * FROM base
UNION ALL
{{ unknown_member('product_key', [
    ('item_id', 'STRING'),
    ('item_name', 'STRING'),
    ('item_brand', 'STRING'),
    ('item_category', 'STRING'),
    ('item_category2', 'STRING'),
    ('item_category3', 'STRING')
]) }}