WITH raw_pairs AS (
    -- Collect both event-level sources (used for sessions) and user-level sources (fallback)
    SELECT DISTINCT
        COALESCE(NULLIF(TRIM(ep_source), ''), 'Unknown') AS raw_source,
        COALESCE(NULLIF(TRIM(ep_medium), ''), 'Unknown') AS raw_medium,
        COALESCE(NULLIF(TRIM(ep_campaign), ''), 'Unknown') AS raw_campaign
    FROM {{ ref('stg_ga4_events') }}
    WHERE ep_source IS NOT NULL OR ep_medium IS NOT NULL OR ep_campaign IS NOT NULL

    UNION DISTINCT

    SELECT DISTINCT
        COALESCE(NULLIF(TRIM(user_raw_source), ''), 'Unknown') AS raw_source,
        COALESCE(NULLIF(TRIM(user_raw_medium), ''), 'Unknown') AS raw_medium,
        COALESCE(NULLIF(TRIM(user_raw_campaign), ''), 'Unknown') AS raw_campaign
    FROM {{ ref('stg_ga4_events') }}
),
normalized AS (
    SELECT DISTINCT
        CASE
            WHEN raw_source IN ('<Other>', '(data deleted)', '(not set)', '') THEN 'Unknown'
            ELSE raw_source
        END AS source,
        CASE
            WHEN raw_medium IN ('<Other>', '(data deleted)', '(not set)', '') THEN 'Unknown'
            ELSE raw_medium
        END AS medium,
        CASE
            WHEN raw_campaign IN ('<Other>', '(data deleted)', '(not set)', '') THEN 'Unknown'
            ELSE raw_campaign
        END AS campaign
    FROM raw_pairs
),
classified AS (
    SELECT
        {{ gen_sk(['source', 'medium', 'campaign']) }} AS traffic_source_key,
        source,
        medium,
        campaign,
        {{ map_channel('LOWER(TRIM(source))', 'LOWER(TRIM(medium))') }} AS channel_code
    FROM normalized
),
base AS (
    SELECT
        traffic_source_key,
        source,
        medium,
        campaign,
        CASE channel_code
            WHEN 'direct' THEN 'Direct'
            WHEN 'organic_search' THEN 'Organic Search'
            WHEN 'paid_search' THEN 'Paid Search'
            WHEN 'display' THEN 'Display'
            WHEN 'email' THEN 'Email'
            WHEN 'affiliate' THEN 'Affiliate'
            WHEN 'paid_social' THEN 'Paid Social'
            WHEN 'social_organic' THEN 'Organic Social'
            WHEN 'referral' THEN 'Referral'
            ELSE 'Unknown'
        END AS channel_group,
        channel_code = 'unassigned' AS is_unassigned
    FROM classified
)
SELECT * FROM base
UNION ALL
{{ unknown_member('traffic_source_key', [
    ('source', 'STRING'),
    ('medium', 'STRING'),
    ('campaign', 'STRING'),
    ('channel_group', 'STRING'),
    ('is_unassigned', 'BOOL')
]) }}