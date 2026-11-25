"""Feature 6 — drill-down along fixed hierarchies (pure pandas).

A drill state is a *path*: the values chosen at each level so far, e.g.
("Referral", "google / referral"). ``subset`` keeps the rows under the path and
``level_table`` aggregates them by the next level.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.dashboard import kpi


@dataclass(frozen=True)
class Level:
    label: str   # Vietnamese name of the level
    column: str  # column of the frame (derived by ``prepare`` for time levels)


@dataclass(frozen=True)
class Hierarchy:
    name: str
    source: str  # "sessions" or "products"
    levels: tuple[Level, ...]
    chronological: bool = False  # order rows by key instead of by size


HIERARCHIES = (
    Hierarchy("Kênh → Nguồn/Medium → Chiến dịch", "sessions", (
        Level("Kênh", "channel_group"),
        Level("Nguồn / Medium", "source_medium"),
        Level("Chiến dịch", "campaign"),
    )),
    Hierarchy("Tháng → Tuần → Ngày", "sessions", (
        Level("Tháng", "month"),
        Level("Tuần", "week"),
        Level("Ngày", "day"),
    ), chronological=True),
    Hierarchy("Nhóm sản phẩm → Sản phẩm", "products", (
        Level("Nhóm sản phẩm", "item_category"),
        Level("Sản phẩm", "item_name"),
    )),
)

PRODUCT_MEASURES = ("item_view_events", "item_add_to_cart_events", "item_checkout_events",
                    "units_sold", "item_revenue_usd")


def prepare(df: pd.DataFrame, hierarchy: Hierarchy) -> pd.DataFrame:
    """Add the time level columns (month, week starting Monday, day) if needed."""
    if hierarchy.levels[0].column != "month":
        return df
    dates = df["session_date"]
    return df.assign(month=dates.dt.to_period("M").dt.start_time,
                     week=dates.dt.to_period("W-SUN").dt.start_time,
                     day=dates)


def subset(df: pd.DataFrame, hierarchy: Hierarchy, path: tuple) -> pd.DataFrame:
    """Rows under ``path`` (one value per level already drilled into)."""
    if len(path) > len(hierarchy.levels):
        raise ValueError(f"path {path!r} is deeper than {hierarchy.name}")
    mask = pd.Series(True, index=df.index)
    for level, value in zip(hierarchy.levels, path):
        mask &= df[level.column] == value
    return df.loc[mask]


def can_drill(hierarchy: Hierarchy, path: tuple) -> bool:
    """True when the rows shown at ``path`` (level ``len(path)``) have children."""
    return len(path) < len(hierarchy.levels) - 1


def level_table(df: pd.DataFrame, hierarchy: Hierarchy, path: tuple) -> pd.DataFrame:
    """Aggregate the rows under ``path`` by the next level.

    Returns
    -------
    pandas.DataFrame
        One row per child with a ``key`` column (the child's value). Sessions
        hierarchies get every KPI of kpi.summarize plus revenue_share_total
        (share of the current node); products hierarchies get the summed
        PRODUCT_MEASURES plus ``revenue_share``. Ordered chronologically for
        time hierarchies, otherwise by size (sessions or revenue).
    """
    level = hierarchy.levels[len(path)]
    rows = subset(df, hierarchy, path)
    if hierarchy.source == "products":
        table = rows.groupby(level.column)[list(PRODUCT_MEASURES)].sum().reset_index()
        total = table["item_revenue_usd"].sum()
        table["revenue_share"] = table["item_revenue_usd"] / total if total else np.nan
        sort_col = "item_revenue_usd"
    else:
        table = kpi.breakdown(rows, level.column)
        sort_col = "sessions"
    table = table.rename(columns={level.column: "key"})
    if table.empty:
        return table
    if hierarchy.chronological:
        return table.sort_values("key", ignore_index=True)
    return table.sort_values(sort_col, ascending=False, ignore_index=True)


def format_key(value, level: Level) -> str:
    """Display text of a level value (time levels as Vietnamese dates)."""
    if level.column == "month":
        return f"Tháng {value:%m/%Y}"
    if level.column == "week":
        end = value + pd.Timedelta(days=6)
        return f"Tuần {value:%d/%m} – {end:%d/%m/%Y}"
    if level.column == "day":
        return f"{value:%d/%m/%Y}"
    return str(value)
