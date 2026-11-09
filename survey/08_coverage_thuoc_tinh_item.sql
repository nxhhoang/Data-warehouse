-- ============================================================
-- Mục #7: Coverage thuộc tính item sau UNNEST(items)
-- Quyết định: hierarchy của dim_product (dùng item_category,
-- category2... hay item_brand; item_id vs item_name)
-- ============================================================

-- 7a. Coverage theo từng sự kiện thương mại điện tử
SELECT
  event_name,
  COUNT(*) AS n_item_rows,
  COUNTIF(it.item_id IS NOT NULL AND it.item_id != '') AS with_item_id,
  COUNTIF(it.item_name IS NOT NULL AND it.item_name != '') AS with_item_name,
  COUNTIF(it.item_brand IS NOT NULL AND it.item_brand != '') AS with_brand,
  COUNTIF(it.item_category IS NOT NULL AND it.item_category != '') AS with_category1,
  COUNTIF(it.item_category2 IS NOT NULL AND it.item_category2 != '') AS with_category2,
  COUNTIF(it.item_category3 IS NOT NULL AND it.item_category3 != '') AS with_category3,
  COUNTIF(it.item_variant IS NOT NULL AND it.item_variant != '') AS with_variant,
  COUNTIF(it.price_in_usd IS NOT NULL) AS with_price_usd,
  COUNTIF(it.quantity IS NOT NULL) AS with_quantity
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`, UNNEST(items) AS it
WHERE event_name IN ('view_item', 'view_item_list', 'add_to_cart', 'begin_checkout', 'purchase')
  AND _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
GROUP BY event_name
ORDER BY n_item_rows DESC;

-- 7b. Số "sản phẩm" phân biệt: theo item_id và theo item_name
-- (nếu item_id thiếu nhiều, dim_product sẽ phải dùng item_name làm khóa tự nhiên)
-- Bôi đen câu này rồi Run selection
SELECT
  COUNT(DISTINCT it.item_id) AS distinct_item_id,
  COUNT(DISTINCT it.item_name) AS distinct_item_name,
  COUNT(DISTINCT CONCAT(it.item_name, '|', IFNULL(it.item_variant, ''))) AS distinct_name_variant
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`, UNNEST(items) AS it
WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131';



-- 7a
-- Row	event_name	n_item_rows	with_item_id	with_item_name	with_brand	with_category1	with_category2	with_category3	with_variant	with_price_usd	with_quantity
-- 1	view_item	2748246	2748246	2748246	2747357	2739652	2748246	2748246	2741354	0	19125
-- 2	add_to_cart	667426	667426	667426	667247	665601	667426	667426	649822	0	37260
-- 3	begin_checkout	77980	77980	77980	76915	74683	77980	77980	77980	0	76047
-- 4	purchase	16003	16003	16003	15790	15773	16003	16003	16003	15555	15555
-- 5	view_item_list	516	516	516	516	516	516	516	516	0	0

-- 7b
-- Row	distinct_item_id	distinct_item_name	distinct_name_variant
-- 1	1394	431	2957