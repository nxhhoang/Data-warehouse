-- ============================================================
-- Mục #2: Danh sách event_name + số lượng từng loại
-- Trả lời: đủ 4 sự kiện phễu (view_item, add_to_cart,
-- begin_checkout, purchase) không, mỗi loại bao nhiêu?
-- ============================================================
SELECT
  event_name,
  COUNT(*) AS n_events,
  COUNT(DISTINCT user_pseudo_id) AS n_users,
  COUNT(DISTINCT event_date) AS n_days_appeared
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
GROUP BY event_name
ORDER BY n_events DESC;


-- Row	event_name	n_events	n_users	n_days_appeared
-- 1	page_view	1350428	269792	92
-- 2	user_engagement	1058721	213004	92
-- 3	scroll	493072	138098	92
-- 4	view_item	386068	61252	92
-- 5	session_start	354970	267116	92
-- 6	first_visit	257462	257314	92
-- 7	view_promotion	190104	102443	92
-- 8	add_to_cart	58543	12545	74
-- 9	begin_checkout	38757	9715	92
-- 10	select_item	31007	13180	70
-- 11	view_search_results	26172	14449	92
-- 12	add_shipping_info	19722	9714	92
-- 13	add_payment_info	13899	5751	92
-- 14	select_promotion	9450	8164	92
-- 15	purchase	5692	4419	92
-- 16	click	1446	1010	92
-- 17	view_item_list	71	44	33