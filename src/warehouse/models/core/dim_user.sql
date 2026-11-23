WITH user_first_event AS (
    SELECT
        user_pseudo_id,
        event_date AS first_seen_date,
        event_ts_utc AS first_seen_ts_utc,
        CASE
            WHEN user_raw_source IN ('<Other>', '(data deleted)', '(not set)', '') OR user_raw_source IS NULL
                THEN 'Unknown'
            ELSE TRIM(user_raw_source)
        END AS first_user_source,
        CASE
            WHEN user_raw_medium IN ('<Other>', '(data deleted)', '(not set)', '') OR user_raw_medium IS NULL
                THEN 'Unknown'
            ELSE TRIM(user_raw_medium)
        END AS first_user_medium,
        CASE
            WHEN user_raw_campaign IN ('<Other>', '(data deleted)', '(not set)', '') OR user_raw_campaign IS NULL
                THEN 'Unknown'
            ELSE TRIM(user_raw_campaign)
        END AS first_user_campaign
    FROM {{ ref('stg_ga4_events') }}
    WHERE user_pseudo_id IS NOT NULL AND TRIM(user_pseudo_id) != ''
    -- Survey 05: 15.64% of users change traffic_source -> lock in values from the first event
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY user_pseudo_id
        ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
    ) = 1
),
user_flags AS (
    SELECT
        user_pseudo_id,
        LOGICAL_OR(event_name = 'first_visit') AS is_new_user
    FROM {{ ref('stg_ga4_events') }}
    WHERE user_pseudo_id IS NOT NULL
    GROUP BY user_pseudo_id
),
base AS (
    SELECT
        {{ gen_sk(['u.user_pseudo_id']) }} AS user_key,
        u.user_pseudo_id,
        u.first_seen_date,
        u.first_seen_ts_utc,
        COALESCE(f.is_new_user, FALSE) AS is_new_user,
        u.first_user_source,
        u.first_user_medium,
        u.first_user_campaign,
        {{ gen_sk(['u.first_user_source', 'u.first_user_medium', 'u.first_user_campaign']) }} AS user_traffic_source_key
    FROM user_first_event u
    LEFT JOIN user_flags f ON u.user_pseudo_id = f.user_pseudo_id
)
SELECT * FROM base
UNION ALL
{{ unknown_member('user_key', [
    ('user_pseudo_id', 'STRING'),
    ('first_seen_date', 'DATE'),
    ('first_seen_ts_utc', 'TIMESTAMP'),
    ('is_new_user', 'BOOL'),
    ('first_user_source', 'STRING'),
    ('first_user_medium', 'STRING'),
    ('first_user_campaign', 'STRING'),
    ('user_traffic_source_key', 'INT64')
]) }}