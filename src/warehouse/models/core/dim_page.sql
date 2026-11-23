{{
    config(
        materialized='table'
    )
}}

WITH extracted_pages AS (
    SELECT
        CASE
            WHEN page_location IS NULL
              OR TRIM(page_location) IN ('', '(not set)', '<Other>', '(data deleted)')
              OR NOT REGEXP_CONTAINS(TRIM(page_location), r'^https?://[^/]+')
            THEN NULL
            ELSE COALESCE(
                NULLIF(REGEXP_EXTRACT(TRIM(page_location), r'^https?://[^/]+(/[^?#]*)'), ''),
                '/'
            )
        END AS page_path,

        REGEXP_EXTRACT(TRIM(page_location), r'^https?://([^/?#]+)') AS page_hostname,
        NULLIF(TRIM(page_title), '') AS page_title
    FROM {{ ref('stg_ga4_events') }}
),

deduplicated_pages AS (
    SELECT
        page_path,

        COALESCE(
            APPROX_TOP_COUNT(page_hostname, 1)[SAFE_OFFSET(0)].value,
            'Unknown'
        ) AS page_hostname,

        COALESCE(
            APPROX_TOP_COUNT(
                IF(page_title IN ('(not set)', '<Other>', '(data deleted)'), NULL, page_title), 1
            )[SAFE_OFFSET(0)].value,
            'Unknown'
        ) AS page_title
    FROM extracted_pages
    WHERE page_path IS NOT NULL
    GROUP BY page_path
),

classified_pages AS (
    SELECT
        page_path,
        page_hostname,
        page_title,

        CASE
            WHEN REGEXP_CONTAINS(LOWER(page_path), r'^/(home|index(\.html)?)?$')
                THEN 'Home'
            WHEN REGEXP_CONTAINS(LOWER(page_path), r'(basket|cart|shopping-cart)')
                THEN 'Cart'
            WHEN REGEXP_CONTAINS(LOWER(page_path), r'(checkout|yourinfo|payment|ordercompleted|thank-you)')
                THEN 'Checkout'
            WHEN REGEXP_CONTAINS(LOWER(page_path), r'(\+detail|/product|/item|/shop/|/apparel|/accessories|/lifestyle|/new|/sale|/clearance|/brands|/campus)')
                THEN 'Product'
            ELSE 'Other'
        END AS page_type
    FROM deduplicated_pages
),

dim_page_base AS (
    SELECT
        {{ gen_sk(['page_path']) }} AS page_sk,
        page_path,
        page_hostname,
        page_title,
        page_type,
        (page_type IN ('Product', 'Cart', 'Checkout')) AS is_funnel_page
    FROM classified_pages
)

SELECT * FROM dim_page_base

UNION ALL

{{ unknown_member(
    sk_col='page_sk',
    columns=[
        ('page_path', 'STRING'),
        ('page_hostname', 'STRING'),
        ('page_title', 'STRING'),
        ('page_type', 'STRING'),
        ('is_funnel_page', 'BOOL')
    ]
) }}