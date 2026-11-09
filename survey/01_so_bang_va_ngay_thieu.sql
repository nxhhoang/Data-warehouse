-- ============================================================
-- Mục #1a: Số bảng trong dataset và kiểm tra ngày thiếu
-- Chỉ đọc metadata (INFORMATION_SCHEMA) → 0 bytes, miễn phí
-- Theo dõi bảng kết quả: n_tables, first_day, last_day, missing_days
-- ============================================================
WITH days AS (
  SELECT
    PARSE_DATE('%Y%m%d', REGEXP_EXTRACT(table_name, r'^events_(\d{8})$')) AS d
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.INFORMATION_SCHEMA.TABLES`
  WHERE table_name LIKE 'events_%'
),
bounds AS (
  SELECT MIN(d) AS min_d, MAX(d) AS max_d FROM days
),
missing AS (
  SELECT g AS d
  FROM bounds, UNNEST(GENERATE_DATE_ARRAY(min_d, max_d)) AS g
  LEFT JOIN days ON days.d = g
  WHERE days.d IS NULL
)
SELECT
  (SELECT COUNT(*) FROM days) AS n_tables,
  (SELECT min_d FROM bounds) AS first_day,
  (SELECT max_d FROM bounds) AS last_day,
  (SELECT COUNT(*) FROM missing) AS n_missing_days,
  (SELECT IFNULL(ARRAY_AGG(FORMAT_DATE('%Y-%m-%d', d) ORDER BY d), ['<không có ngày thiếu>']) FROM missing) AS missing_days;


-- Row  n_tables	first_day	last_day	n_missing_days	missing_days
-- 1	92	2020-11-01	2021-01-31	0	<không có ngày thiếu>