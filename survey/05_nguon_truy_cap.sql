-- ============================================================
-- Mục #4: Phân bố traffic_source và tính chất quy kết cấp user
-- Quyết định: giữ hay thu hẹp câu hỏi Q3 (so sánh nguồn truy cập)
-- Lưu ý schema: traffic_source = nguồn thu hút người dùng LẦN ĐẦU
-- (cấp user), không phải nguồn cấp phiên
-- ============================================================

-- 4a. Phân bố source/medium theo số user phân biệt
-- (đếm user chứ không đếm event vì traffic_source là thuộc tính user)
SELECT
  IFNULL(NULLIF(traffic_source.source, '(not set)'), '(not set)') AS source,
  IFNULL(NULLIF(traffic_source.medium, '(not set)'), '(not set)') AS medium,
  COUNT(DISTINCT user_pseudo_id) AS n_users
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
GROUP BY source, medium
ORDER BY n_users DESC
LIMIT 200;

-- 4b. Kiểm chứng quy kết cấp user: mỗi user có bao nhiêu cặp source/medium khác nhau?
-- Kỳ vọng: gần như tất cả user có đúng 1 cpair → xác nhận traffic_source không đổi theo phiên
-- Bôi đen câu này rồi Run selection
WITH per_user AS (
  SELECT
    user_pseudo_id,
    COUNT(DISTINCT CONCAT('|', IFNULL(traffic_source.source, ''), '|', IFNULL(traffic_source.medium, ''), '|')) AS n_source_medium_pairs
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
  GROUP BY user_pseudo_id
)
SELECT
  n_source_medium_pairs,
  COUNT(*) AS n_users,
  ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_users
FROM per_user
GROUP BY n_source_medium_pairs
ORDER BY n_source_medium_pairs;


-- SELECT IFNULL ... 
-- Row	source	medium	n_users
-- 1	google	organic	103487
-- 2	(direct)	(none)	75951
-- 3	<Other>	<Other>	51037
-- 4	<Other>	referral	32880
-- 5	shop.googlemerchandisestore.com	referral	26065
-- 6	(data deleted)	(data deleted)	17948
-- 7	google	cpc	15527
-- 8	<Other>	organic	10095
-- 9	<Other>	(data deleted)	393
-- 10	(data deleted)	referral	3
-- 11	google	<Other>	1
-- 12	<Other>	cpc	1

-- WITH per_user AS...
-- Row	n_source_medium_pairs	n_users	pct_users
-- 1	1	227894	84.36
-- 2	2	29029	10.75
-- 3	3	7940	2.94
-- 4	4	3384	1.25
-- 5	5	1430	0.53
-- 6	6	412	0.15
-- 7	7	62	0.02
-- 8	8	3	0.0