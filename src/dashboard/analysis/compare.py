"""Feature 3 — performance comparison (pure pandas).

Two modes: several groups of one dimension side by side (channels,
campaigns...), or the same filtered slice over two periods.
"""

import numpy as np
import pandas as pd

from src.dashboard import kpi
from src.dashboard.filters import Filters, apply_filters

# KPIs shown when comparing; ranking can use any of them
COMPARE_KPIS = (
    "sessions", "users", "engagement_rate", "conversion_rate", "orders",
    "revenue_usd", "aov_usd", "revenue_per_session_usd",
)
RANK_KPIS = ("revenue_usd", "conversion_rate", "revenue_per_session_usd")

Period = tuple[pd.Timestamp, pd.Timestamp]


def compare_groups(df: pd.DataFrame, by: str, groups: list[str], rank_by: str,
                   min_sessions: int = 100) -> pd.DataFrame:
    """KPIs for the chosen ``groups`` of ``by``, ranked by ``rank_by``.

    Groups under ``min_sessions`` are kept but flagged (``small_sample``) and
    ranked after the others, so a 3-session campaign with one order cannot
    top a conversion ranking.
    """
    table = kpi.breakdown(df[df[by].isin(groups)], by)
    if table.empty:
        return table
    table["small_sample"] = table["sessions"] < min_sessions
    table = table.sort_values(["small_sample", rank_by], ascending=[True, False],
                              na_position="last", ignore_index=True)
    table["rank"] = np.arange(1, len(table) + 1)
    return table


def default_periods(start: pd.Timestamp, end: pd.Timestamp,
                    data_start: pd.Timestamp) -> tuple[Period, Period]:
    """Default (A, B) for period comparison: A before B.

    B is the selected range and A the period before it (kpi.previous_period).
    When A would start before the data, the selected range is split into
    two halves instead. A one-day boundary range keeps its own date for B
    and leaves A outside the data window, since it has no earlier relative
    period to compare against.
    """
    prev = kpi.previous_period(start, end)
    if prev[0] >= data_start:
        return prev, (start, end)
    if start == end:
        # A one-day range at the data boundary cannot be split into two halves.
        return (start - pd.Timedelta(days=1), start), (start, end)
    days = (end - start).days + 1
    half = max(days // 2, 1)
    mid = start + pd.Timedelta(days=half - 1)
    return (start, mid), (mid + pd.Timedelta(days=1), end)


def compare_periods(sessions: pd.DataFrame, filters: Filters,
                    a: Period, b: Period) -> pd.DataFrame:
    """The sidebar's dimension filters applied to two periods.

    Returns
    -------
    pandas.DataFrame
        Index = KPI id (COMPARE_KPIS); columns ``a``, ``b`` and ``change``
        (relative change from A to B).
    """
    sa = kpi.summarize(apply_filters(sessions, filters.with_dates(*a)))
    sb = kpi.summarize(apply_filters(sessions, filters.with_dates(*b)))
    rows = [{"kpi": k, "a": sa[k], "b": sb[k], "change": kpi.relative_change(sb[k], sa[k])}
            for k in COMPARE_KPIS]
    return pd.DataFrame(rows).set_index("kpi")


def aligned_daily(sessions: pd.DataFrame, filters: Filters, a: Period, b: Period,
                  kpi_id: str, labels: tuple[str, str] = ("Kỳ A", "Kỳ B")) -> pd.DataFrame:
    """Daily values of one KPI for both periods, aligned on day number.

    Returns
    -------
    pandas.DataFrame
        Long format: ``day`` (1, 2, ...), ``period`` (label), ``date``, ``value``.
    """
    parts = []
    for label, (start, end) in zip(labels, (a, b)):
        series = kpi.time_series(apply_filters(sessions, filters.with_dates(start, end)),
                                 kpi_id, "Ngày")
        series = series.rename(columns={"period": "date"})
        series["day"] = (series["date"] - start).dt.days + 1
        series["period"] = label
        parts.append(series)
    return pd.concat(parts, ignore_index=True)[["day", "period", "date", "value"]]
