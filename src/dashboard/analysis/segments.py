"""Feature 7 — customer segmentation (pure pandas).

Segments come from any session dimension (device, geography, source, new vs
returning, engagement level). Each segment is profiled against the filtered
average, and two dimensions can be crossed in a matrix.
"""

import numpy as np
import pandas as pd

from src.dashboard import kpi

# Engagement levels from engagement_time_msec. On the real data the top level
# (> 5 min, 6% of sessions) converts at 16% and brings ~89% of revenue, while
# sessions under 10 s almost never buy, so the cut points separate behaviour.
ENGAGEMENT_BINS = (-1, 0, 10_000, 60_000, 300_000, np.inf)
ENGAGEMENT_LEVELS = ("Không tương tác (0s)", "Rất thấp (1–10s)", "Thấp (10–60s)",
                     "Trung bình (1–5 phút)", "Cao (> 5 phút)")

PROFILE_KPIS = ("sessions", "users", "engagement_rate", "conversion_rate", "aov_usd",
                "revenue_per_session_usd", "revenue_usd")
CROSS_KPIS = ("conversion_rate", "revenue_per_session_usd", "sessions", "revenue_usd")


def engagement_level(engagement_time_msec: pd.Series) -> pd.Series:
    """Map engagement time (ms) to an ordered engagement level label."""
    return pd.cut(engagement_time_msec, ENGAGEMENT_BINS, labels=ENGAGEMENT_LEVELS).astype("string")


def segment_profile(df: pd.DataFrame, by: str, order: tuple[str, ...] | None = None) -> pd.DataFrame:
    """KPIs per segment plus each segment's weight and index against the average.

    Returns
    -------
    pandas.DataFrame
        kpi.breakdown(df, by) plus ``session_share`` and ``revenue_share_total``
        (shares of the filtered total) and ``cr_index`` / ``rps_index``
        (conversion rate and revenue per session divided by the overall value;
        1.0 = average). Ordered by ``order`` when given, else by sessions.
    """
    table = kpi.breakdown(df, by)
    if table.empty:
        return table
    overall = kpi.summarize(df)
    table["session_share"] = table["sessions"] / table["sessions"].sum()
    table["cr_index"] = table["conversion_rate"] / overall["conversion_rate"] \
        if overall["conversion_rate"] else np.nan
    table["rps_index"] = table["revenue_per_session_usd"] / overall["revenue_per_session_usd"] \
        if overall["revenue_per_session_usd"] else np.nan
    if order:
        rank = {v: i for i, v in enumerate(order)}
        table = table.sort_values(by, key=lambda s: s.map(rank).fillna(len(rank)), ignore_index=True)
    return table


def cross_tab(df: pd.DataFrame, rows: str, cols: str, kpi_id: str,
              min_sessions: int = 100, top: int = 8) -> tuple[pd.DataFrame, pd.DataFrame]:
    """KPI matrix of two dimensions.

    Only the ``top`` largest values of each dimension are kept (by sessions),
    and cells under ``min_sessions`` are NaN so a handful of sessions cannot
    produce an extreme rate.

    Returns
    -------
    values : pandas.DataFrame
        Index = ``rows`` values, columns = ``cols`` values, cells = the KPI.
    sessions : pandas.DataFrame
        Same shape, session counts per cell.
    """
    keep_rows = df[rows].value_counts().index[:top]
    keep_cols = df[cols].value_counts().index[:top]
    part = df[df[rows].isin(keep_rows) & df[cols].isin(keep_cols)]
    values = pd.DataFrame(np.nan, index=keep_rows, columns=keep_cols, dtype=float)
    sessions = pd.DataFrame(0, index=keep_rows, columns=keep_cols, dtype=int)
    for (r, c), cell in part.groupby([rows, cols], sort=False):
        sessions.loc[r, c] = len(cell)
        if len(cell) >= min_sessions:
            values.loc[r, c] = kpi.summarize(cell)[kpi_id]
    return values, sessions
