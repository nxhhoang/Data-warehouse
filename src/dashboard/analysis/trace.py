"""Feature 10 — number traceability (pure pandas, plus SQL text for BigQuery).

For a KPI under the current filters this module gives: the numerator and
denominator behind the value, the source sessions that make it up, the
lineage path from kpi_dictionary.yaml, and a SQL query that recomputes the
same components straight from the Core layer for an independent check.
"""

import pandas as pd

from src.dashboard import kpi
from src.dashboard.filters import USER_TYPES, Filters

# Base measures of kpi.totals: display label, session-level condition of the
# sessions that contribute to it, and the SQL expression over core.fct_sessions.
BASE = {
    "sessions": ("Tổng số phiên", None, "COUNT(*)"),
    "users": ("Số người dùng phân biệt", None, "COUNT(DISTINCT s.user_key)"),
    "new_users": ("Người dùng có first_visit", "is_new_user",
                  "COUNT(DISTINCT IF(u.is_new_user, s.user_key, NULL))"),
    "engaged_sessions": ("Phiên có tương tác", "is_engaged", "SUM(s.is_engaged)"),
    "page_views": ("Lượt page_view", "page_view_count", "SUM(s.page_view_count)"),
    "view_item_events": ("Sự kiện view_item", "view_item_count", "SUM(s.view_item_count)"),
    "s_view": ("Phiên có view_item", "has_view_item", "SUM(s.has_view_item)"),
    "s_cart": ("Phiên có add_to_cart", "has_add_to_cart", "SUM(s.has_add_to_cart)"),
    "s_checkout": ("Phiên có begin_checkout", "has_begin_checkout", "SUM(s.has_begin_checkout)"),
    "s_ship": ("Phiên có add_shipping_info", "has_add_shipping_info",
               "SUM(s.has_add_shipping_info)"),
    "s_pay": ("Phiên có add_payment_info", "has_add_payment_info",
              "SUM(s.has_add_payment_info)"),
    "s_buy": ("Phiên có giao dịch hợp lệ", "has_purchase", "SUM(s.has_purchase)"),
    "s_cart_buy": ("Phiên có add_to_cart và giao dịch hợp lệ", "has_add_to_cart",
                   "COUNTIF(s.has_add_to_cart = 1 AND s.has_purchase = 1)"),
    "s_pay_buy": ("Phiên có add_payment_info và giao dịch hợp lệ", "has_add_payment_info",
                  "COUNTIF(s.has_add_payment_info = 1 AND s.has_purchase = 1)"),
    "orders": ("Số giao dịch hợp lệ", "order_count", "SUM(s.order_count)"),
    "revenue_usd": ("Doanh thu giao dịch hợp lệ (USD)", "order_count", "SUM(s.revenue_usd)"),
}

# KPI id -> (numerator, denominator or None, formula shape)
COMPONENTS = {
    "users": ("users", None, "value"),
    "sessions": ("sessions", None, "value"),
    "sessions_per_user": ("sessions", "users", "ratio"),
    "page_views": ("page_views", None, "value"),
    "engagement_rate": ("engaged_sessions", "sessions", "ratio"),
    "new_user_rate": ("new_users", "users", "ratio"),
    "view_item_events": ("view_item_events", None, "value"),
    "add_to_cart_rate": ("s_cart", "s_view", "ratio"),
    "begin_checkout_rate": ("s_checkout", "s_cart", "ratio"),
    "shipping_info_rate": ("s_ship", "s_checkout", "ratio"),
    "payment_info_rate": ("s_pay", "s_ship", "ratio"),
    "purchase_completion_rate": ("s_pay_buy", "s_pay", "ratio"),
    "cart_abandonment_rate": ("s_cart_buy", "s_cart", "one_minus_ratio"),
    "orders": ("orders", None, "value"),
    "conversion_rate": ("s_buy", "sessions", "ratio"),
    "revenue_usd": ("revenue_usd", None, "value"),
    "aov_usd": ("revenue_usd", "orders", "ratio"),
    "revenue_per_session_usd": ("revenue_usd", "sessions", "ratio"),
    "revenue_per_user_usd": ("revenue_usd", "users", "ratio"),
}

RECORD_COLUMNS = ("session_id", "session_date", "channel_group", "source_medium", "campaign",
                  "device_category", "country", "user_type")


def traceable_kpis() -> list[str]:
    """KPI ids that can be traced, in dictionary order."""
    return [k for k in kpi.kpi_dictionary() if k in COMPONENTS]


def components(df: pd.DataFrame, kpi_id: str) -> dict:
    """Numerator, denominator and recomputed value of ``kpi_id`` for ``df``.

    Returns
    -------
    dict
        ``numerator`` and ``denominator`` as (label, value) (denominator None
        for plain counts), ``shape`` and ``value`` (equal to kpi.summarize).
    """
    num_key, den_key, shape = COMPONENTS[kpi_id]
    t = kpi.totals(df)
    num = t[num_key]
    den = t[den_key] if den_key else None
    if shape == "value":
        value = num
    else:
        ratio = num / den if den else float("nan")
        value = 1 - ratio if shape == "one_minus_ratio" else ratio
    return {
        "numerator": (BASE[num_key][0], num),
        "denominator": (BASE[den_key][0], den) if den_key else None,
        "shape": shape,
        "value": value,
    }


def source_records(df: pd.DataFrame, kpi_id: str) -> pd.DataFrame:
    """Sessions behind the KPI: the denominator's population (or the numerator's
    for plain counts), largest revenue first.

    For a rate this is every session the rate is measured over, with the
    numerator flag as a column, so the numerator is the count of 1s.
    """
    num_key, den_key, _ = COMPONENTS[kpi_id]
    population = BASE[den_key or num_key][1]
    rows = df if population is None else df[df[population] > 0]
    flags = [BASE[k][1] for k in (num_key, den_key) if k and BASE[k][1]]
    cols = [*RECORD_COLUMNS, *dict.fromkeys(flags), "order_count", "revenue_usd"]
    cols = list(dict.fromkeys(c for c in cols if c in rows.columns))
    return rows.sort_values(["revenue_usd", "session_id"], ascending=[False, True])[cols]


def lineage(kpi_id: str) -> list[tuple[str, str]]:
    """(layer, objects) from source to dashboard, read from kpi_dictionary.yaml."""
    meta = kpi.kpi_dictionary()[kpi_id]
    num_key, den_key, _ = COMPONENTS[kpi_id]
    uses_orders = {"s_buy", "s_cart_buy", "s_pay_buy", "orders", "revenue_usd"} & {num_key, den_key}
    staging = "stg_ga4_events" + (" + stg_valid_orders" if uses_orders else "")
    return [
        ("Nguồn", meta["raw_source"]),
        ("Staging", staging),
        ("Core", " + ".join(meta["core_tables"])),
        ("Mart / KPI", meta["mart_table"]),
        ("Dashboard", f"kpi.summarize → {kpi_id}"),
    ]


def lineage_dot(kpi_id: str) -> str:
    """Graphviz DOT of the lineage path, left to right."""
    steps = lineage(kpi_id)
    nodes = "\n".join(
        f'  n{i} [label="{layer}\\n{obj.replace(chr(34), chr(39))}"];' for i, (layer, obj) in enumerate(steps))
    edges = " -> ".join(f"n{i}" for i in range(len(steps)))
    return ("digraph lineage {\n  rankdir=LR; bgcolor=transparent;\n"
            '  node [shape=box, style="rounded", fontname="sans-serif", fontsize=11];\n'
            f"{nodes}\n  {edges};\n}}")


def verification_sql(kpi_id: str, filters: Filters, project: str) -> tuple[str, list[tuple]]:
    """SQL recomputing the KPI's components from the Core layer with the same filters.

    Returns
    -------
    sql : str
        Standard SQL with named parameters.
    params : list of tuple
        (name, BigQuery type, value) for bigquery.ScalarQueryParameter /
        ArrayQueryParameter (list values are arrays).
    """
    num_key, den_key, _ = COMPONENTS[kpi_id]
    select = [f"{BASE[num_key][2]} AS numerator"]
    if den_key:
        select.append(f"{BASE[den_key][2]} AS denominator")
    where = ["d.full_date BETWEEN @start_date AND @end_date"]
    params: list[tuple] = [("start_date", "DATE", filters.start.date()),
                           ("end_date", "DATE", filters.end.date())]
    for column, values, name in (("ts.channel_group", filters.channels, "channels"),
                                 ("dev.device_category", filters.devices, "devices"),
                                 ("geo.country", filters.countries, "countries"),
                                 ("ts.campaign", filters.campaigns, "campaigns")):
        if values:
            where.append(f"{column} IN UNNEST(@{name})")
            params.append((name, "STRING", list(values)))
    if filters.source_mediums:
        where.append("CONCAT(ts.source, ' / ', ts.medium) IN UNNEST(@source_mediums)")
        params.append(("source_mediums", "STRING", list(filters.source_mediums)))
    if filters.user_type == USER_TYPES[1]:
        where.append("s.is_new_user_session = 1")
    elif filters.user_type == USER_TYPES[2]:
        where.append("s.is_new_user_session = 0")
    sql = f"""SELECT
    {(',' + chr(10) + '    ').join(select)}
FROM `{project}.core.fct_sessions` s
JOIN `{project}.core.dim_date` d ON s.date_key = d.date_key
JOIN `{project}.core.dim_traffic_source` ts ON s.session_source_key = ts.traffic_source_key
JOIN `{project}.core.dim_device` dev ON s.device_key = dev.device_key
JOIN `{project}.core.dim_geo` geo ON s.geo_key = geo.geo_key
JOIN `{project}.core.dim_user` u ON s.user_key = u.user_key
WHERE {(chr(10) + '  AND ').join(where)}"""
    return sql, params
