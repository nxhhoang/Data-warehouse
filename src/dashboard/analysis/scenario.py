"""Feature 9 — scenario simulation (pure pandas).

Starting from each channel's historical performance in the filtered period,
the user changes traffic and conversion rate by a percentage; orders and
revenue are re-estimated with the same orders per purchasing session and the
same average order value. There is no cost data, so the model says nothing
about the spend needed to reach the new traffic.
"""

import numpy as np
import pandas as pd

from src.dashboard import kpi


def baseline(df: pd.DataFrame, by: str = "channel_group") -> pd.DataFrame:
    """Historical performance per group, the starting point of a scenario.

    Returns
    -------
    pandas.DataFrame
        Columns ``by``, ``sessions``, ``conversion_rate``, ``purchasing_sessions``,
        ``orders_per_purchase`` (orders per purchasing session), ``orders``,
        ``aov_usd`` and ``revenue_usd``; by sessions, descending.
    """
    rows = []
    for key, part in df.groupby(by, sort=False):
        t = kpi.totals(part)
        rows.append({
            by: key,
            "sessions": t["sessions"],
            "conversion_rate": t["s_buy"] / t["sessions"] if t["sessions"] else np.nan,
            "purchasing_sessions": t["s_buy"],
            "orders_per_purchase": t["orders"] / t["s_buy"] if t["s_buy"] else np.nan,
            "orders": t["orders"],
            "aov_usd": t["revenue_usd"] / t["orders"] if t["orders"] else np.nan,
            "revenue_usd": t["revenue_usd"],
        })
    out = pd.DataFrame(rows)
    return out.sort_values("sessions", ascending=False, ignore_index=True) if not out.empty else out


def simulate(base: pd.DataFrame, by: str, traffic_change: dict, cr_change: dict) -> pd.DataFrame:
    """Apply relative changes per group (0.1 = +10%) and re-estimate outcomes.

    New purchasing sessions = new sessions × conversion rate × (1 + CR change),
    with the conversion rate capped at 100%; orders and revenue follow with the
    group's historical orders per purchasing session and AOV. Groups that never
    sold keep zero orders whatever the changes.

    Returns
    -------
    pandas.DataFrame
        ``base`` plus ``traffic_change``, ``cr_change``, ``sessions_new``,
        ``conversion_rate_new``, ``orders_new``, ``revenue_new``,
        ``delta_orders`` and ``delta_revenue``.
    """
    out = base.copy()
    out["traffic_change"] = out[by].map(traffic_change).fillna(0.0)
    out["cr_change"] = out[by].map(cr_change).fillna(0.0)
    out["sessions_new"] = out["sessions"] * (1 + out["traffic_change"]).clip(lower=0)
    out["conversion_rate_new"] = (out["conversion_rate"] * (1 + out["cr_change"])).clip(0, 1)
    purchases = out["sessions_new"] * out["conversion_rate_new"].fillna(0)
    out["orders_new"] = purchases * out["orders_per_purchase"].fillna(0)
    out["revenue_new"] = out["orders_new"] * out["aov_usd"].fillna(0)
    out["delta_orders"] = out["orders_new"] - out["orders"]
    out["delta_revenue"] = out["revenue_new"] - out["revenue_usd"]
    return out


def totals(result: pd.DataFrame) -> dict[str, float]:
    """Baseline and scenario totals across all groups."""
    return {
        "orders": result["orders"].sum(),
        "orders_new": result["orders_new"].sum(),
        "revenue": result["revenue_usd"].sum(),
        "revenue_new": result["revenue_new"].sum(),
        "sessions": result["sessions"].sum(),
        "sessions_new": result["sessions_new"].sum(),
    }
