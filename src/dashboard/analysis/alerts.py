"""Feature 8 — threshold alerts (pure pandas).

Each group (channel, campaign, source / medium) is compared between the
current window and the window of the same length just before it. A rule
fires when its relative change crosses the user threshold; the alert is
"serious" at twice the threshold.
"""

from dataclasses import dataclass

import pandas as pd

from src.dashboard import kpi

WARNING = "Cảnh báo"
SERIOUS = "Nghiêm trọng"

Window = tuple[pd.Timestamp, pd.Timestamp]


@dataclass(frozen=True)
class Thresholds:
    """Relative thresholds (0.2 = 20%) chosen by the user."""

    drop: float = 0.2    # conversion rate, revenue or sessions falling by at least this
    rise: float = 0.2    # cart abandonment rising by at least this
    spike: float = 0.5   # sessions rising by at least this with no conversion gain


@dataclass(frozen=True)
class Rule:
    name: str
    kpi_id: str
    direction: str  # "drop" or "rise"


RULES = (
    Rule("Tỷ lệ chuyển đổi giảm", "conversion_rate", "drop"),
    Rule("Doanh thu giảm", "revenue_usd", "drop"),
    Rule("Số phiên giảm", "sessions", "drop"),
    Rule("Tỷ lệ rời bỏ giỏ hàng tăng", "cart_abandonment_rate", "rise"),
)
SPIKE_RULE = "Lưu lượng tăng đột biến, chuyển đổi không tăng"


def windows(end: pd.Timestamp, days: int) -> tuple[Window, Window]:
    """(previous, current): the last ``days`` days up to ``end`` and the days before."""
    current = (end - pd.Timedelta(days=days - 1), end)
    previous = (current[0] - pd.Timedelta(days=days), current[0] - pd.Timedelta(days=1))
    return previous, current


def _by_group(df: pd.DataFrame, by: str) -> dict:
    return {key: kpi.summarize(part) for key, part in df.groupby(by, sort=False)}


def evaluate(previous: pd.DataFrame, current: pd.DataFrame, by: str,
             thresholds: Thresholds, min_sessions: int = 100,
             cart_previous: pd.DataFrame | None = None,
             cart_current: pd.DataFrame | None = None) -> pd.DataFrame:
    """Alerts for every group of ``by`` present in both windows.

    Parameters
    ----------
    previous, current : pandas.DataFrame
        Session frames of the two windows (already filtered).
    by : str
        Grouping column.
    thresholds : Thresholds
        User thresholds.
    min_sessions : int, optional
        Groups under this many sessions in either window are skipped.
    cart_previous, cart_current : pandas.DataFrame, optional
        Frames used for the cart abandonment rule; pass the windows restricted
        to days with add_to_cart tracking so missing days do not fake a rise.
        Default: ``previous`` and ``current``.

    Returns
    -------
    pandas.DataFrame
        One row per alert: ``group``, ``rule``, ``kpi_id``, ``previous``,
        ``current``, ``change``, ``severity``; most severe first.
    """
    prev, cur = _by_group(previous, by), _by_group(current, by)
    cart_prev = _by_group(cart_previous, by) if cart_previous is not None else prev
    cart_cur = _by_group(cart_current, by) if cart_current is not None else cur
    rows = []
    for group in prev.keys() & cur.keys():
        p, c = prev[group], cur[group]
        if p["sessions"] < min_sessions or c["sessions"] < min_sessions:
            continue
        for rule in RULES:
            src_p, src_c = (cart_prev, cart_cur) if rule.kpi_id == "cart_abandonment_rate" else (prev, cur)
            if group not in src_p or group not in src_c:
                continue
            before, after = src_p[group][rule.kpi_id], src_c[group][rule.kpi_id]
            change = kpi.relative_change(after, before)
            if pd.isna(change):
                continue
            limit = thresholds.drop if rule.direction == "drop" else thresholds.rise
            crossed = -change if rule.direction == "drop" else change
            if crossed >= limit:
                rows.append(_alert(group, rule.name, rule.kpi_id, before, after, change,
                                   SERIOUS if crossed >= 2 * limit else WARNING))
        traffic = kpi.relative_change(c["sessions"], p["sessions"])
        cr_change = kpi.relative_change(c["conversion_rate"], p["conversion_rate"])
        # Zero baseline is a special case: relative_change is undefined, so use
        # absolute conversion instead of letting NaN look like "no gain".
        no_gain = (c["conversion_rate"] <= p["conversion_rate"]
                   if p["conversion_rate"] == 0 else not (cr_change > 0))
        if traffic >= thresholds.spike and no_gain:
            rows.append(_alert(group, SPIKE_RULE, "sessions", p["sessions"], c["sessions"], traffic,
                               SERIOUS if traffic >= 2 * thresholds.spike else WARNING))
    out = pd.DataFrame(rows, columns=["group", "rule", "kpi_id", "previous", "current",
                                      "change", "severity"])
    if out.empty:
        return out
    out["_serious"] = out["severity"] == SERIOUS
    out["_size"] = out["change"].abs()
    return (out.sort_values(["_serious", "_size"], ascending=False)
               .drop(columns=["_serious", "_size"]).reset_index(drop=True))


def _alert(group, rule, kpi_id, before, after, change, severity) -> dict:
    return {"group": group, "rule": rule, "kpi_id": kpi_id, "previous": before,
            "current": after, "change": change, "severity": severity}
