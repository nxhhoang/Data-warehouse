-- ============================================================
-- Mục #1b: Quy mô dữ liệu — tổng event, tổng user, mốc thời gian
-- Quét toàn bộ dataset (vài GB) → bật dry-run trước
-- ============================================================
SELECT
  COUNT(*) AS total_events,
  COUNT(DISTINCT user_pseudo_id) AS total_users,
  COUNT(DISTINCT event_date) AS n_days,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_MICROS(MIN(event_timestamp))) AS first_event_time_utc,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_MICROS(MAX(event_timestamp))) AS last_event_time_utc
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131';

-- Số event theo từng ngày (kiểm tra biến động theo mùa vụ — Black Friday, Giáng sinh)
-- Bôi đen câu này rồi Run selection
SELECT
  PARSE_DATE('%Y%m%d', event_date) AS event_day,
  COUNT(*) AS n_events,
  COUNT(DISTINCT user_pseudo_id) AS n_users
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
GROUP BY event_date
ORDER BY event_date;


-- SELECT COUNT...
-- Row	total_events	total_users	n_days	first_event_time_utc	last_event_time_utc
-- 1	4295584	270154	92	2020-11-01 00:00:04	2021-01-31 23:59:55

-- SELECT PARSE
-- Row	event_day	n_events	n_users
-- 1	2020-11-01	31272	2365
-- 2	2020-11-02	48388	3262
-- 3	2020-11-03	61672	4648
-- 4	2020-11-04	51866	3734
-- 5	2020-11-05	51952	3272
-- 6	2020-11-06	49004	2813
-- 7	2020-11-07	34309	2004
-- 8	2020-11-08	30137	1919
-- 9	2020-11-09	44756	2805
-- 10	2020-11-10	51195	3260
-- 11	2020-11-11	51941	3296
-- 12	2020-11-12	49166	3179
-- 13	2020-11-13	50358	2860
-- 14	2020-11-14	34039	2076
-- 15	2020-11-15	31195	1957
-- 16	2020-11-16	49320	3085
-- 17	2020-11-17	59789	3449
-- 18	2020-11-18	55456	3505
-- 19	2020-11-19	53932	3566
-- 20	2020-11-20	57894	3477
-- 21	2020-11-21	41980	2755
-- 22	2020-11-22	36446	2359
-- 23	2020-11-23	52844	3421
-- 24	2020-11-24	62971	3821
-- 25	2020-11-25	64469	3988
-- 26	2020-11-26	54681	3626
-- 27	2020-11-27	54254	3512
-- 28	2020-11-28	44643	3010
-- 29	2020-11-29	42169	2887
-- 30	2020-11-30	70614	3971
-- 31	2020-12-01	71804	4308
-- 32	2020-12-02	66832	4101
-- 33	2020-12-03	71689	4464
-- 34	2020-12-04	69393	4131
-- 35	2020-12-05	49528	3082
-- 36	2020-12-06	42828	2948
-- 37	2020-12-07	71632	4709
-- 38	2020-12-08	92199	6689
-- 39	2020-12-09	82315	5531
-- 40	2020-12-10	80855	5241
-- 41	2020-12-11	75780	4948
-- 42	2020-12-12	56146	3750
-- 43	2020-12-13	46886	3402
-- 44	2020-12-14	66082	4552
-- 45	2020-12-15	72774	4992
-- 46	2020-12-16	67497	4820
-- 47	2020-12-17	63887	4711
-- 48	2020-12-18	56742	4261
-- 49	2020-12-19	37342	3236
-- 50	2020-12-20	30071	2966