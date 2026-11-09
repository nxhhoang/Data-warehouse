-- ============================================================
-- Mục #8: Phiên vắt qua nửa đêm
-- Quyết định: quy ước gán ngày cho phiên (gán theo ngày
-- sự kiện đầu tiên của phiên và ghi nhận trong từ điển)
-- ============================================================
WITH ev AS (
  SELECT
    user_pseudo_id,
    (SELECT ANY_VALUE(value.int_value) FROM UNNEST(event_params) WHERE key = 'ga_session_id' AND value.int_value IS NOT NULL) AS ga_session_id,
    event_date
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
),
sess AS (
  SELECT
    user_pseudo_id,
    ga_session_id,
    COUNT(DISTINCT event_date) AS n_event_dates
  FROM ev
  WHERE ga_session_id IS NOT NULL
  GROUP BY user_pseudo_id, ga_session_id
)
SELECT
  COUNT(*) AS n_sessions_total,
  COUNTIF(n_event_dates = 1) AS single_day_sessions,
  COUNTIF(n_event_dates > 1) AS midnight_spanning_sessions,
  ROUND(100 * COUNTIF(n_event_dates > 1) / COUNT(*), 2) AS pct_midnight_spanning
FROM sess;


-- Row	n_sessions_total	single_day_sessions	midnight_spanning_sessions	pct_midnight_spanning
-- 1	360129	359284	845	0.23