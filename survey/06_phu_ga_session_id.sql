-- ============================================================
-- Mục #5: Tỷ lệ event có ga_session_id trong event_params
-- Quyết định: có dựng được phiên đáng tin cậy theo
-- (user_pseudo_id + ga_session_id) không
-- ============================================================
SELECT
  event_name,
  COUNT(*) AS n_events,
    COUNTIF(
    (SELECT ANY_VALUE(value.int_value)
    FROM UNNEST(event_params)
    WHERE key = 'ga_session_id'
      AND value.int_value IS NOT NULL) IS NOT NULL
  ) AS n_with_ga_session_id,
  ROUND(
    100 * COUNTIF(
      (SELECT ANY_VALUE(value.int_value) FROM UNNEST(event_params) WHERE key = 'ga_session_id' AND value.int_value IS NOT NULL) IS NOT NULL
    ) / COUNT(*), 2
  ) AS pct_with_ga_session_id
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
GROUP BY event_name
ORDER BY n_events DESC;


-- Row	event_name	n_events	n_with_ga_session_id	pct_with_ga_session_id
-- 1	page_view	1350428	1350428	100.0
-- 2	user_engagement	1058721	1058721	100.0
-- 3	scroll	493072	493072	100.0
-- 4	view_item	386068	386068	100.0
-- 5	session_start	354970	354970	100.0
-- 6	first_visit	257462	257462	100.0
-- 7	view_promotion	190104	190104	100.0
-- 8	add_to_cart	58543	58543	100.0
-- 9	begin_checkout	38757	38757	100.0
-- 10	select_item	31007	31007	100.0
-- 11	view_search_results	26172	26172	100.0
-- 12	add_shipping_info	19722	19722	100.0
-- 13	add_payment_info	13899	13899	100.0
-- 14	select_promotion	9450	9450	100.0
-- 15	purchase	5692	5692	100.0
-- 16	click	1446	1446	100.0
-- 17	view_item_list	71	71	100.0