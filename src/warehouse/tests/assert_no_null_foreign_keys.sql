-- Test: No fact table is allowed to contain NULL foreign keys (all must be >= -1)
SELECT 'fct_events' AS table_name, COUNT(*) AS null_fk_rows
FROM {{ ref('fct_events') }}
WHERE date_key IS NULL OR event_key IS NULL OR user_key IS NULL
   OR device_key IS NULL OR geo_key IS NULL OR page_key IS NULL OR traffic_source_key IS NULL
HAVING COUNT(*) > 0

UNION ALL

SELECT 'fct_sessions' AS table_name, COUNT(*) AS null_fk_rows
FROM {{ ref('fct_sessions') }}
WHERE date_key IS NULL OR user_key IS NULL OR device_key IS NULL
   OR geo_key IS NULL OR landing_page_key IS NULL OR session_source_key IS NULL OR user_source_key IS NULL
HAVING COUNT(*) > 0

UNION ALL

SELECT 'fct_purchase_items' AS table_name, COUNT(*) AS null_fk_rows
FROM {{ ref('fct_purchase_items') }}
WHERE date_key IS NULL OR user_key IS NULL OR device_key IS NULL
   OR geo_key IS NULL OR traffic_source_key IS NULL OR product_key IS NULL
HAVING COUNT(*) > 0

UNION ALL

SELECT 'fct_item_events' AS table_name, COUNT(*) AS null_fk_rows
FROM {{ ref('fct_item_events') }}
WHERE date_key IS NULL OR event_key IS NULL OR user_key IS NULL
   OR device_key IS NULL OR geo_key IS NULL OR traffic_source_key IS NULL OR product_key IS NULL
HAVING COUNT(*) > 0