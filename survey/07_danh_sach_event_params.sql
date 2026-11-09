-- ============================================================
-- Mục #6: Toàn bộ event_params key xuất hiện trong dataset
-- Quyết định: phạm vi quy kết nguồn — có key nguồn cấp phiên
-- (source/medium/session_source...) trong event_params không?
-- Kỳ vọng theo schema cũ: KHÔNG có
-- ============================================================
SELECT
  EP.key AS event_param_key,
  COUNT(*) AS n_occurrences,
  COUNT(DISTINCT event_name) AS n_event_types,
  STRING_AGG(DISTINCT event_name, ', ' ORDER BY event_name LIMIT 8) AS sample_event_types
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`, UNNEST(event_params) AS EP
WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
GROUP BY event_param_key
ORDER BY n_occurrences DESC;


-- Row	event_param_key	n_occurrences	n_event_types	sample_event_types
-- 1	ga_session_id	4295584	17	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, first_visit, page_view, purchase
-- 2	ga_session_number	4295584	17	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, first_visit, page_view, purchase
-- 3	page_location	4295584	17	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, first_visit, page_view, purchase
-- 4	page_title	4276104	17	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, first_visit, page_view, purchase
-- 5	engaged_session_event	4116237	17	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, first_visit, page_view, purchase
-- 6	session_engaged	3996312	17	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, first_visit, page_view, purchase
-- 7	debug_mode	3682991	15	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, page_view, purchase, scroll
-- 8	page_referrer	3206512	17	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, first_visit, page_view, purchase
-- 9	all_data	2828174	15	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, page_view, purchase, scroll
-- 10	clean_event	2828040	14	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, page_view, purchase, scroll
-- 11	engagement_time_msec	2431818	14	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, page_view, purchase, scroll
-- 12	medium	1439214	15	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, page_view, purchase, scroll
-- 13	campaign	1439167	15	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, page_view, purchase, scroll
-- 14	source	1428080	15	add_payment_info, add_shipping_info, add_to_cart, begin_checkout, click, page_view, purchase, scroll
-- 15	percent_scrolled	493072	1	scroll
-- 16	term	338704	12	add_to_cart, begin_checkout, click, page_view, scroll, select_item, select_promotion, user_engagement
-- 17	entrances	332179	1	page_view
-- 18	gclid	118481	10	add_to_cart, click, page_view, scroll, select_item, select_promotion, user_engagement, view_item
-- 19	gclsrc	116846	10	add_to_cart, click, page_view, scroll, select_item, select_promotion, user_engagement, view_item
-- 20	currency	39313	3	add_payment_info, add_shipping_info, purchase
-- 21	search_term	26172	1	view_search_results
-- 22	unique_search_term	20967	1	view_search_results
-- 23	dclid	15701	8	add_to_cart, page_view, scroll, select_item, user_engagement, view_item, view_item_list, view_promotion
-- 24	tax	5242	1	purchase
-- 25	transaction_id	5242	1	purchase
-- 26	payment_type	5242	1	purchase
-- 27	value	5242	1	purchase
-- 28	shipping_tier	4159	1	purchase
-- 29	coupon	3075	1	purchase
-- 30	promotion_name	2270	1	purchase
-- 31	outbound	1446	1	click
-- 32	link_domain	1446	1	click
-- 33	link_url	1446	1	click
-- 34	link_classes	6	1	click