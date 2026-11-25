{# Partitioning is off by default: BigQuery Sandbox expires partitions older than
   60 days, so 2020 partitions would be deleted as soon as they are written.
   Enable with --vars '{partition_tables: true}' on a billing-enabled project. #}
{{
    config(
        partition_by=({"field": "event_date", "data_type": "date"}
                      if var("partition_tables", false) else none),
        cluster_by=["event_key", "traffic_source_key"]
    )
}}

SELECT
    e.event_id,
    COALESCE(d.date_key, -1) AS date_key,
    COALESCE(ev.event_key, -1) AS event_key,
    COALESCE(u.user_key, -1) AS user_key,
    COALESCE(dev.device_key, -1) AS device_key,
    COALESCE(geo.geo_key, -1) AS geo_key,
    COALESCE(pg.page_key, -1) AS page_key,
    COALESCE(s.session_source_key, u.user_traffic_source_key, -1) AS traffic_source_key,
    COALESCE(e.session_id, 'Unknown') AS session_id,
    e.event_date,
    e.event_timestamp,
    e.event_ts_utc,
    e.engagement_time_msec
FROM {{ ref('stg_ga4_events') }} e
LEFT JOIN {{ ref('dim_date') }} d ON e.date_key = d.date_key
LEFT JOIN {{ ref('dim_event') }} ev ON TRIM(e.event_name) = ev.event_name
LEFT JOIN {{ ref('dim_user') }} u ON e.user_pseudo_id = u.user_pseudo_id
LEFT JOIN {{ ref('dim_device') }} dev
    ON {{ gen_sk([
        "CASE WHEN e.device_category IN ('<Other>', '(data deleted)', '(not set)', '') OR e.device_category IS NULL THEN 'Unknown' ELSE TRIM(e.device_category) END",
        "CASE WHEN e.operating_system IN ('<Other>', '(data deleted)', '(not set)', '') OR e.operating_system IS NULL THEN 'Unknown' ELSE TRIM(e.operating_system) END",
        "CASE WHEN e.browser IN ('<Other>', '(data deleted)', '(not set)', '') OR e.browser IS NULL THEN 'Unknown' ELSE TRIM(e.browser) END",
        "CASE WHEN e.language IN ('<Other>', '(data deleted)', '(not set)', '') OR e.language IS NULL THEN 'Unknown' ELSE TRIM(e.language) END"
    ]) }} = dev.device_key
LEFT JOIN {{ ref('dim_geo') }} geo
    ON {{ gen_sk([
        "CASE WHEN e.continent IN ('<Other>', '(data deleted)', '(not set)', '') OR e.continent IS NULL THEN 'Unknown' ELSE TRIM(e.continent) END",
        "CASE WHEN e.country IN ('<Other>', '(data deleted)', '(not set)', '') OR e.country IS NULL THEN 'Unknown' ELSE TRIM(e.country) END",
        "CASE WHEN e.region IN ('<Other>', '(data deleted)', '(not set)', '') OR e.region IS NULL THEN 'Unknown' ELSE TRIM(e.region) END",
        "CASE WHEN e.city IN ('<Other>', '(data deleted)', '(not set)', '') OR e.city IS NULL THEN 'Unknown' ELSE TRIM(e.city) END"
    ]) }} = geo.geo_key
LEFT JOIN {{ ref('dim_page') }} pg
    ON {{ gen_sk(["REGEXP_REPLACE(TRIM(e.page_location), r'[?#].*$', '')"]) }} = pg.page_key
LEFT JOIN {{ ref('fct_sessions') }} s ON e.session_id = s.session_id