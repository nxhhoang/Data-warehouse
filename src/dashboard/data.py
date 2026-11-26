"""Data access layer: the only module of the dashboard that reads data.

Every page works on two pandas DataFrames whose columns are fixed below:

- ``sessions``: one row per session, built from ``core.fct_sessions`` joined
  with its dimensions (~360k rows, loaded once and filtered in memory, so
  every filter combination can count distinct users).
- ``products``: product measures from ``marts.fct_product_channel_daily``
  joined with its conformed dimensions at date × product × session source ×
  device grain.

Two sources return the same columns: ``mock`` (src/dashboard/mock.py, no GCP
needed) and ``bigquery`` (the warehouse built by NXHH, datasets core / marts).
Ratios are never stored: pages compute them from the additive columns after
filtering (src/dashboard/kpi.py).
"""

import numpy as np
import pandas as pd

from src.dashboard.config import Settings
from src.extract.bigquery_usage import DEFAULT_USAGE_LOG, prepare_query, record_job

# Column name -> pandas dtype. Both sources are coerced to exactly this schema.
SESSION_COLUMNS = {
    "session_id": "string",
    "user_key": "int64",
    "session_date": "datetime64[ns]",
    "is_weekend": "bool",
    "is_holiday_season": "bool",
    "is_add_to_cart_tracked": "bool",
    "channel_group": "string",
    "source": "string",
    "medium": "string",
    "campaign": "string",
    "attribution_basis": "string",
    "device_category": "string",
    "operating_system": "string",
    "continent": "string",
    "country": "string",
    "landing_page_type": "string",
    # User-level flag from dim_user (user has a first_visit in the window);
    # used by the new_user_rate KPI, same as kpi.v_kpi_traffic_engagement.
    "is_new_user": "bool",
    # Session-level: 1 if the session holds the user's first_visit (new),
    # 0 for every later session (returning). Drives the user-type filter.
    "is_new_user_session": "int64",
    # GA4 ga_session_number: 1, 2, 3... per user, counting sessions before the window
    "user_session_number": "int64",
    "event_count": "int64",
    "page_view_count": "int64",
    "view_item_count": "int64",
    "engagement_time_msec": "int64",
    "is_engaged": "int64",
    "has_view_item": "int64",
    "has_add_to_cart": "int64",
    "has_begin_checkout": "int64",
    "has_add_shipping_info": "int64",
    "has_add_payment_info": "int64",
    "has_purchase": "int64",
    "order_count": "int64",
    "revenue_usd": "float64",
}

PRODUCT_COLUMNS = {
    "date": "datetime64[ns]",
    "item_id": "string",
    "item_name": "string",
    "item_brand": "string",
    "item_category": "string",
    "channel_group": "string",
    "device_category": "string",
    "source_medium": "string",
    "campaign": "string",
    "item_view_events": "int64",
    "item_add_to_cart_events": "int64",
    "item_checkout_events": "int64",
    "units_sold": "int64",
    "item_revenue_usd": "float64",
}

SESSIONS_SQL = """
SELECT
    s.session_id,
    s.user_key,
    d.full_date AS session_date,
    d.is_weekend,
    d.is_holiday_season,
    d.is_add_to_cart_tracked,
    ts.channel_group,
    ts.source,
    ts.medium,
    ts.campaign,
    s.attribution_basis,
    dev.device_category,
    dev.operating_system,
    geo.continent,
    geo.country,
    COALESCE(pg.page_type, 'Unknown') AS landing_page_type,
    u.is_new_user,
    s.is_new_user_session,
    s.user_session_number,
    s.event_count,
    s.page_view_count,
    s.view_item_count,
    s.engagement_time_msec,
    s.is_engaged,
    s.has_view_item,
    s.has_add_to_cart,
    s.has_begin_checkout,
    s.has_add_shipping_info,
    s.has_add_payment_info,
    s.has_purchase,
    s.order_count,
    CAST(s.revenue_usd AS FLOAT64) AS revenue_usd
FROM `{project}.core.fct_sessions` s
JOIN `{project}.core.dim_date` d ON s.date_key = d.date_key
JOIN `{project}.core.dim_traffic_source` ts ON s.session_source_key = ts.traffic_source_key
JOIN `{project}.core.dim_device` dev ON s.device_key = dev.device_key
JOIN `{project}.core.dim_geo` geo ON s.geo_key = geo.geo_key
JOIN `{project}.core.dim_user` u ON s.user_key = u.user_key
LEFT JOIN `{project}.core.dim_page` pg ON s.landing_page_key = pg.page_key
WHERE s.date_key > 0
"""

PRODUCTS_SQL = """
SELECT
    d.full_date AS date,
    p.item_id,
    p.item_name,
    p.item_brand,
    p.item_category,
    ts.channel_group,
    dev.device_category,
    CONCAT(ts.source, ' / ', ts.medium) AS source_medium,
    ts.campaign,
    SUM(f.item_view_events) AS item_view_events,
    SUM(f.item_add_to_cart_events) AS item_add_to_cart_events,
    SUM(f.item_checkout_events) AS item_checkout_events,
    SUM(f.units_sold) AS units_sold,
    CAST(SUM(f.item_revenue_usd) AS FLOAT64) AS item_revenue_usd
FROM `{project}.marts.fct_product_channel_daily` f
JOIN `{project}.core.dim_date` d ON f.date_key = d.date_key
JOIN `{project}.core.dim_product` p ON f.product_key = p.product_key
JOIN `{project}.core.dim_traffic_source` ts ON f.session_source_key = ts.traffic_source_key
JOIN `{project}.core.dim_device` dev ON f.device_key = dev.device_key
WHERE f.date_key > 0
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
"""


def coerce(df: pd.DataFrame, schema: dict[str, str]) -> pd.DataFrame:
    """Return ``df`` restricted and cast to ``schema``.

    BigQuery returns DATE as ``dbdate``, INT64 as nullable ``Int64`` and
    may return NULLs; this makes both sources look identical to the pages.

    Raises
    ------
    KeyError
        If a column required by the schema is missing.
    """
    missing = [c for c in schema if c not in df.columns]
    if missing:
        raise KeyError(f"Missing columns from data source: {missing}")
    out = df[list(schema)].copy()
    for col, dtype in schema.items():
        if dtype.startswith("datetime"):
            out[col] = pd.to_datetime(out[col])
        elif dtype == "string":
            out[col] = out[col].fillna("Unknown").astype("string")
        elif dtype == "bool":
            out[col] = out[col].fillna(False).astype(bool)
        else:
            out[col] = out[col].fillna(0).astype(dtype)
    return out


# Columns added after loading, for grouping in the analysis pages
DERIVED_SESSION_COLUMNS = ("source_medium", "user_type", "engagement_level")


def derive_session_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add DERIVED_SESSION_COLUMNS to a coerced session frame."""
    out = df.copy()
    out["source_medium"] = (out["source"] + " / " + out["medium"]).astype("string")
    out["user_type"] = pd.Series(
        np.where(out["is_new_user_session"] == 1, "Người dùng mới", "Người dùng cũ"),
        index=out.index, dtype="string")
    from src.dashboard.analysis.segments import engagement_level

    out["engagement_level"] = engagement_level(out["engagement_time_msec"])
    return out


def _query_bigquery(sql: str, project_id: str,
                    max_query_bytes: int = 128 * 1024**2,
                    usage_log=DEFAULT_USAGE_LOG) -> pd.DataFrame:
    if not project_id:
        raise ValueError("GCP_PROJECT_ID is empty; set it in .env to read BigQuery")
    # Imported lazily so the mock mode and the tests need no GCP packages
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    job = prepare_query(client, sql.format(project=project_id), None,
                        max_query_bytes, "dashboard", usage_log)
    try:
        return job.to_dataframe()
    finally:
        record_job(job, "dashboard", usage_log)


def run_query(settings: Settings, sql: str, params: list[tuple]) -> pd.DataFrame:
    """Run a parameterised query on BigQuery (traceability checks).

    Parameters
    ----------
    params : list of tuple
        (name, BigQuery type, value); a list value becomes an ARRAY parameter.
    """
    if settings.data_source != "bigquery":
        raise ValueError("run_query needs DASHBOARD_DATA_SOURCE=bigquery")
    from google.cloud import bigquery

    query_params = [
        bigquery.ArrayQueryParameter(n, t, v) if isinstance(v, list)
        else bigquery.ScalarQueryParameter(n, t, v)
        for n, t, v in params
    ]
    client = bigquery.Client(project=settings.project_id)
    job = prepare_query(client, sql, query_params, settings.max_query_bytes,
                        "dashboard_trace", settings.usage_log)
    try:
        return job.to_dataframe()
    finally:
        record_job(job, "dashboard_trace", settings.usage_log)


def load_sessions(settings: Settings) -> pd.DataFrame:
    """Load the session-level frame from the configured source."""
    if settings.data_source == "bigquery":
        raw = _query_bigquery(SESSIONS_SQL, settings.project_id,
                              settings.max_query_bytes, settings.usage_log)
    else:
        from src.dashboard.mock import make_sessions

        raw = make_sessions()
    return derive_session_columns(coerce(raw, SESSION_COLUMNS))


def load_products(settings: Settings) -> pd.DataFrame:
    """Load the date × product × channel × device frame from the configured source."""
    if settings.data_source == "bigquery":
        raw = _query_bigquery(PRODUCTS_SQL, settings.project_id,
                              settings.max_query_bytes, settings.usage_log)
    else:
        from src.dashboard.mock import make_products

        raw = make_products()
    return coerce(raw, PRODUCT_COLUMNS)
