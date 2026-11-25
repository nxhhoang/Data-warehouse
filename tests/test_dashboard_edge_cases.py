"""Regression tests for dashboard period and alert edge cases."""

import pandas as pd

from src.dashboard.analysis.alerts import SPIKE_RULE, Thresholds, evaluate
from src.dashboard.analysis.compare import default_periods


def test_single_day_comparison_has_no_reversed_period():
    day = pd.Timestamp("2020-11-01")
    a, b = default_periods(day, day, pd.Timestamp("2020-11-01"))
    assert b == (day, day)
    assert a[0] <= a[1]
    assert b[0] <= b[1]
    assert a[1] <= b[0]


def _channel_sessions(count: int, purchases: int) -> pd.DataFrame:
    return pd.DataFrame({
        "channel_group": ["Organic Search"] * count,
        "user_key": [f"u{i}" for i in range(count)],
        "is_new_user": [True] * count,
        "is_engaged": [True] * count,
        "page_view_count": [1] * count,
        "view_item_count": [0] * count,
        "has_view_item": [False] * count,
        "has_add_to_cart": [False] * count,
        "has_begin_checkout": [False] * count,
        "has_add_shipping_info": [False] * count,
        "has_add_payment_info": [False] * count,
        "has_purchase": [i < purchases for i in range(count)],
        "order_count": [int(i < purchases) for i in range(count)],
        "revenue_usd": [10.0 if i < purchases else 0.0 for i in range(count)],
    })


def test_spike_alert_not_falsely_fired_when_conversion_leaves_zero():
    previous = _channel_sessions(100, purchases=0)
    current = _channel_sessions(150, purchases=20)
    alerts = evaluate(previous, current, by="channel_group",
                      thresholds=Thresholds(), min_sessions=1)
    assert SPIKE_RULE not in alerts["rule"].tolist()


def test_spike_alert_fires_when_traffic_grows_without_conversion():
    previous = _channel_sessions(100, purchases=0)
    current = _channel_sessions(150, purchases=0)
    alerts = evaluate(previous, current, by="channel_group",
                      thresholds=Thresholds(), min_sessions=1)
    assert SPIKE_RULE in alerts["rule"].tolist()
