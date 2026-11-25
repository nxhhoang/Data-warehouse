"""Feature 5 — 6-step conversion funnel on the session frame (pure pandas).

The funnel counts "sessions that reached step k", without enforcing order:
the warehouse only has per-session has_* flags, and add_to_cart is missing on
18/92 days, so 1,471 purchasing sessions have no add_to_cart. Step rates are
the dictionary KPIs (kpi.summarize), so they match kpi.v_kpi_funnel.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.dashboard import kpi


@dataclass(frozen=True)
class Step:
    flag: str          # has_* column of the session frame
    label: str         # Vietnamese label shown to users
    event: str         # GA4 event name
    rate_kpi: str | None  # dictionary KPI for the transition into this step


STEPS = (
    Step("has_view_item", "Xem sản phẩm", "view_item", None),
    Step("has_add_to_cart", "Thêm vào giỏ", "add_to_cart", "add_to_cart_rate"),
    Step("has_begin_checkout", "Bắt đầu thanh toán", "begin_checkout", "begin_checkout_rate"),
    Step("has_add_shipping_info", "Thông tin giao hàng", "add_shipping_info", "shipping_info_rate"),
    Step("has_add_payment_info", "Thông tin thanh toán", "add_payment_info", "payment_info_rate"),
    Step("has_purchase", "Mua hàng", "purchase", "purchase_completion_rate"),
)


def tracked_days_only(df: pd.DataFrame) -> pd.DataFrame:
    """Sessions on days where add_to_cart was recorded (74/92 days)."""
    return df.loc[df["is_add_to_cart_tracked"]]


def funnel_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per step.

    Returns
    -------
    pandas.DataFrame
        Columns: ``label``, ``event``, ``sessions`` (sessions with the step),
        ``step_rate`` (dictionary KPI from the previous step, NaN for the
        first), ``drop_rate`` (1 - step_rate) and ``share_of_first``
        (sessions / sessions with view_item).
    """
    summary = kpi.summarize(df)
    first = df[STEPS[0].flag].sum()
    rows = []
    for step in STEPS:
        sessions = int(df[step.flag].sum())
        rate = summary[step.rate_kpi] if step.rate_kpi else np.nan
        rows.append({
            "label": step.label,
            "event": step.event,
            "sessions": sessions,
            "step_rate": rate,
            # Unordered counting can push a rate a hair above 100% (one session
            # with add_shipping_info but no begin_checkout); no negative drop-off
            "drop_rate": max(0.0, 1 - rate) if not pd.isna(rate) else np.nan,
            "share_of_first": sessions / first if first else np.nan,
        })
    return pd.DataFrame(rows)


def weakest_step(table: pd.DataFrame) -> pd.Series | None:
    """The transition with the lowest step rate (highest drop-off), if any."""
    rated = table.dropna(subset=["step_rate"])
    if rated.empty:
        return None
    return rated.loc[rated["step_rate"].idxmin()]


def step_rates_by(df: pd.DataFrame, by: str, min_sessions: int = 100) -> pd.DataFrame:
    """Step rates per value of ``by``, one row per segment.

    Segments with fewer than ``min_sessions`` view_item sessions are dropped:
    their rates swing on a handful of sessions.

    Returns
    -------
    pandas.DataFrame
        Index ``by``; columns ``view_sessions``, one column per transition
        (step label) and ``conversion_rate``; sorted by view_sessions.
    """
    rows = []
    for key, part in df.groupby(by, sort=False):
        views = int(part[STEPS[0].flag].sum())
        if views < min_sessions:
            continue
        summary = kpi.summarize(part)
        row = {by: key, "view_sessions": views}
        row.update({s.label: summary[s.rate_kpi] for s in STEPS if s.rate_kpi})
        row["conversion_rate"] = summary["conversion_rate"]
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=[by, "view_sessions"]).set_index(by)
    out = pd.DataFrame(rows).set_index(by)
    return out.sort_values("view_sessions", ascending=False)


def product_stage_table(products: pd.DataFrame, by: str = "item_category") -> pd.DataFrame:
    """Item-level counts per product group, without cross-stage ratios.

    In the obfuscated dataset the items seen in view_item/add_to_cart and the
    items purchased are almost disjoint catalogues (4 of 427 viewed item_ids
    were ever sold), so a per-product view -> purchase rate is meaningless.
    Only checkout and purchase share item_ids, hence ``units_per_checkout``.
    """
    cols = ["item_view_events", "item_add_to_cart_events", "item_checkout_events",
            "units_sold", "item_revenue_usd"]
    out = products.groupby(by)[cols].sum()
    out["units_per_checkout"] = out["units_sold"] / out["item_checkout_events"].replace(0, np.nan)
    return out.sort_values("item_revenue_usd", ascending=False)
