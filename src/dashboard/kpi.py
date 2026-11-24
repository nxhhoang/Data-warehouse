"""KPI calculations on the session-level frame (pure pandas, no Streamlit).

Every formula mirrors ``sql_formula`` in src/kpi/kpi_dictionary.yaml, the
single source of truth for KPI definitions. Ratios are always recomputed from
additive numerators/denominators *after* filtering and grouping; ratio
columns from the kpi.v_kpi_* views are never summed or averaged.
"""

from functools import lru_cache

import numpy as np
import pandas as pd
import yaml

from src.dashboard.config import KPI_DICTIONARY_PATH

# KPIs whose denominator involves add_to_cart (missing on 18/92 days)
CART_DEPENDENT = ("add_to_cart_rate", "begin_checkout_rate", "cart_abandonment_rate")

# Period aliases; "W-SUN" = weeks ending Sunday, i.e. starting Monday
GRAINS = {"Ngày": "D", "Tuần": "W-SUN", "Tháng": "M"}


@lru_cache(maxsize=1)
def kpi_dictionary() -> dict[str, dict]:
    """KPI id -> definition entry of kpi_dictionary.yaml."""
    with open(KPI_DICTIONARY_PATH, encoding="utf-8") as f:
        return {item["id"]: item for item in yaml.safe_load(f)["kpis"]}


def label(kpi_id: str) -> str:
    """Vietnamese KPI name from the dictionary."""
    return kpi_dictionary()[kpi_id]["name"]


def unit(kpi_id: str) -> str:
    """KPI unit from the dictionary ('%', 'USD', 'phiên', ...)."""
    return kpi_dictionary()[kpi_id]["unit"]


def _div(num: float, den: float) -> float:
    """SAFE_DIVIDE: NaN instead of an error when the denominator is 0."""
    return float(num) / float(den) if den else np.nan


def totals(df: pd.DataFrame) -> dict[str, float]:
    """Additive base measures of a frame of sessions."""
    return {
        "sessions": len(df),
        "users": df["user_key"].nunique(),
        "new_users": df.loc[df["is_new_user"], "user_key"].nunique(),
        "engaged_sessions": df["is_engaged"].sum(),
        "page_views": df["page_view_count"].sum(),
        "view_item_events": df["view_item_count"].sum(),
        "s_view": df["has_view_item"].sum(),
        "s_cart": df["has_add_to_cart"].sum(),
        "s_checkout": df["has_begin_checkout"].sum(),
        "s_ship": df["has_add_shipping_info"].sum(),
        "s_pay": df["has_add_payment_info"].sum(),
        "s_buy": df["has_purchase"].sum(),
        "s_cart_buy": (df["has_add_to_cart"] & df["has_purchase"]).sum(),
        "s_pay_buy": (df["has_add_payment_info"] & df["has_purchase"]).sum(),
        "orders": df["order_count"].sum(),
        "revenue_usd": df["revenue_usd"].sum(),
    }


def summarize(df: pd.DataFrame) -> dict[str, float]:
    """Compute every session-based KPI of the dictionary for ``df``.

    Returns
    -------
    dict
        KPI id -> value. Rates are fractions (0.05 = 5%); undefined ratios
        are NaN. ``revenue_share_total`` is relative to ``df`` itself and is
        computed by :func:`breakdown` instead.
    """
    t = totals(df)
    return {
        "users": t["users"],
        "sessions": t["sessions"],
        "sessions_per_user": _div(t["sessions"], t["users"]),
        "page_views": t["page_views"],
        "engagement_rate": _div(t["engaged_sessions"], t["sessions"]),
        "new_user_rate": _div(t["new_users"], t["users"]),
        "view_item_events": t["view_item_events"],
        "add_to_cart_rate": _div(t["s_cart"], t["s_view"]),
        "begin_checkout_rate": _div(t["s_checkout"], t["s_cart"]),
        "shipping_info_rate": _div(t["s_ship"], t["s_checkout"]),
        "payment_info_rate": _div(t["s_pay"], t["s_ship"]),
        "purchase_completion_rate": _div(t["s_pay_buy"], t["s_pay"]),
        "cart_abandonment_rate": 1 - _div(t["s_cart_buy"], t["s_cart"]),
        "orders": t["orders"],
        "conversion_rate": _div(t["s_buy"], t["sessions"]),
        "revenue_usd": t["revenue_usd"],
        "aov_usd": _div(t["revenue_usd"], t["orders"]),
        "revenue_per_session_usd": _div(t["revenue_usd"], t["sessions"]),
        "revenue_per_user_usd": _div(t["revenue_usd"], t["users"]),
    }


# Date ranges where the source records (almost) no valid order, so orders and
# revenue fall for data reasons rather than business ones. Counts from the raw
# GA4 tables: 883 purchases over the 92 days have transaction_id '(not set)'
# (USD 31,817 excluded by the valid-order rule).
DATA_GAPS = (
    (pd.Timestamp("2020-11-01"), pd.Timestamp("2020-11-10"),
     "01–10/11/2020: mọi sự kiện purchase trong dữ liệu gốc có transaction_id '(not set)', nên "
     "không có giao dịch hợp lệ; đơn hàng và doanh thu các ngày này bằng 0 do quy tắc lọc, không "
     "phải do sụt giảm thật."),
    (pd.Timestamp("2021-01-26"), pd.Timestamp("2021-01-31"),
     "26–31/01/2021: dữ liệu gốc ngừng ghi nhận giao dịch bình thường (232/282 purchase không có "
     "transaction_id, tổng doanh thu gốc 6 ngày chỉ 2.193 USD so với 3.000–6.700 USD/ngày trước "
     "đó); mức giảm đơn hàng và doanh thu ở cuối kỳ là do dữ liệu, không phải do kinh doanh."),
)
ORDER_KPIS = ("orders", "conversion_rate", "revenue_usd", "aov_usd",
              "revenue_per_session_usd", "revenue_per_user_usd", "purchase_completion_rate")


def data_gap_note(start: pd.Timestamp, end: pd.Timestamp) -> str | None:
    """Warning text for every data gap that [start, end] overlaps, or None."""
    notes = [text for first, last, text in DATA_GAPS if not (start > last or end < first)]
    return " ".join(notes) or None


def time_series(df: pd.DataFrame, kpi_id: str, grain: str) -> pd.DataFrame:
    """One KPI per time bucket.

    Parameters
    ----------
    df : pandas.DataFrame
        Filtered session-level frame.
    kpi_id : str
        Any key returned by :func:`summarize`.
    grain : str
        A label of :data:`GRAINS` ('Ngày', 'Tuần', 'Tháng').

    Returns
    -------
    pandas.DataFrame
        Columns ``period`` and ``value``. For daily grain, cart-dependent KPIs
        are NaN on days without add_to_cart tracking (never interpolated).
    """
    freq = GRAINS[grain]
    period = df["session_date"].dt.to_period(freq).dt.start_time
    rows = []
    for start, part in df.groupby(period, sort=True):
        value = summarize(part)[kpi_id]
        if (grain == "Ngày" and kpi_id in CART_DEPENDENT
                and not part["is_add_to_cart_tracked"].any()):
            value = np.nan
        rows.append({"period": start, "value": value})
    return pd.DataFrame(rows, columns=["period", "value"])


def breakdown(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """KPIs per value of a dimension column, with revenue share.

    ``revenue_share_total`` is computed against the filtered total, unlike
    the kpi.v_kpi_conversion_revenue view whose share spans the whole table.
    """
    rows = [{by: key, **summarize(part)} for key, part in df.groupby(by, sort=False)]
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    total = out["revenue_usd"].sum()
    out["revenue_share_total"] = out["revenue_usd"] / total if total else np.nan
    return out.sort_values("sessions", ascending=False, ignore_index=True)


def previous_period(start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The comparison period immediately before [start, end].

    Whole calendar months compare with the same number of preceding calendar
    months (December -> November, even though their lengths differ); any
    other range compares with the range of equal length just before it.
    """
    if start.is_month_start and end.is_month_end:
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        prev_start = start - pd.DateOffset(months=months)
        return prev_start, start - pd.Timedelta(days=1)
    length = end - start + pd.Timedelta(days=1)
    return start - length, start - pd.Timedelta(days=1)


def relative_change(current: float, previous: float) -> float:
    """(current - previous) / previous, NaN when undefined."""
    if previous is None or pd.isna(previous) or previous == 0 or pd.isna(current):
        return np.nan
    return (current - previous) / abs(previous)
