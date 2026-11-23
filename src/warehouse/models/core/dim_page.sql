WITH cleaned_pages AS (
    SELECT
        -- Strip query strings and fragments to normalize the page URL
        REGEXP_REPLACE(TRIM(page_location), r'[?#].*$', '') AS normalized_url,
        NULLIF(TRIM(page_title), '') AS page_title
    FROM {{ ref('stg_ga4_events') }}
    WHERE page_location IS NOT NULL AND TRIM(page_location) != ''
),
aggregated AS (
    SELECT
        normalized_url AS page_location,
        COALESCE(REGEXP_EXTRACT(normalized_url, r'^https?://([^/]+)'), 'Unknown') AS page_host,
        COALESCE(NULLIF(REGEXP_EXTRACT(normalized_url, r'^https?://[^/]+(/.*)$'), ''), '/') AS page_path,
        COALESCE(APPROX_TOP_COUNT(page_title, 1)[OFFSET(0)].value, 'Unknown') AS page_title
    FROM cleaned_pages
    GROUP BY normalized_url
),
base AS (
    SELECT
        {{ gen_sk(['page_location']) }} AS page_key,
        page_location,
        page_host,
        page_path,
        page_title,
        CASE
            WHEN page_path IN ('/', '/home', '/index.html') THEN 'home'
            WHEN REGEXP_CONTAINS(LOWER(page_path), r'cart|basket') THEN 'cart'
            WHEN REGEXP_CONTAINS(LOWER(page_path), r'checkout|payment|order') THEN 'checkout'
            WHEN REGEXP_CONTAINS(LOWER(page_path), r'product|item|shop|store|apparel|accessories|drinkware|office') THEN 'product'
            ELSE 'other'
        END AS page_type
    FROM aggregated
)
SELECT * FROM base
UNION ALL
{{ unknown_member('page_key', [
    ('page_location', 'STRING'),
    ('page_host', 'STRING'),
    ('page_path', 'STRING'),
    ('page_title', 'STRING'),
    ('page_type', 'STRING')
]) }}