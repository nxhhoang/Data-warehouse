"""Unit tests for the dashboard analysis modules (features 3, 4, 5).

Pure pandas, no Streamlit or GCP. Run from the repository root:
    pytest tests/test_dashboard_analysis.py
"""

import math

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("yaml")

from src.dashboard import kpi  # noqa: E402
from src.dashboard.analysis import channel_quality as cq  # noqa: E402
from src.dashboard.analysis import compare, funnel  # noqa: E402
from src.dashboard.config import Settings  # noqa: E402
from src.dashboard.data import SESSION_COLUMNS, coerce, derive_session_columns  # noqa: E402
from src.dashboard.data import load_products, load_sessions  # noqa: E402
from src.dashboard.filters import Filters  # noqa: E402

MOCK = Settings("mock", "", 0.2)
STRINGS = ("channel_group", "source", "medium", "campaign", "attribution_basis",
           "device_category", "operating_system", "continent", "country", "landing_page_type")


@pytest.fixture(scope="module")
def sessions():
    return load_sessions(MOCK)


def _frame(*rows):
    """Session frame from partial rows; unspecified measures are 0."""
    full = []
    for i, overrides in enumerate(rows):
        row = {c: 0 for c in SESSION_COLUMNS}
        row.update({c: "Unknown" for c in STRINGS})
        row.update(session_id=f"s{i}", user_key=i, session_date="2020-11-02",
                   is_weekend=False, is_holiday_season=False, is_add_to_cart_tracked=True,
                   is_new_user=False, revenue_usd=0.0, user_session_number=1)
        row.update(overrides)
        full.append(row)
    return derive_session_columns(coerce(pd.DataFrame(full), SESSION_COLUMNS))


def _sessions_with(n, **flags):
    return [dict(flags) for _ in range(n)]


# ---------- funnel ----------

def test_funnel_table_counts_and_rates_match_kpi(sessions):
    table = funnel.funnel_table(sessions)
    assert list(table["label"]) == [s.label for s in funnel.STEPS]
    assert table.loc[0, "sessions"] == sessions["has_view_item"].sum()
    assert math.isnan(table.loc[0, "step_rate"])
    summary = kpi.summarize(sessions)
    assert table.loc[1, "step_rate"] == pytest.approx(summary["add_to_cart_rate"])
    assert table.loc[5, "step_rate"] == pytest.approx(summary["purchase_completion_rate"])
    assert table.loc[3, "drop_rate"] == pytest.approx(1 - summary["shipping_info_rate"])


def test_weakest_step_is_lowest_transition():
    df = _frame(
        *_sessions_with(10, has_view_item=1),
        *_sessions_with(5, has_view_item=1, has_add_to_cart=1),
        *_sessions_with(4, has_view_item=1, has_add_to_cart=1, has_begin_checkout=1,
                        has_add_shipping_info=1),
        *_sessions_with(1, has_view_item=1, has_add_to_cart=1, has_begin_checkout=1,
                        has_add_shipping_info=1, has_add_payment_info=1, has_purchase=1,
                        order_count=1),
    )
    weakest = funnel.weakest_step(funnel.funnel_table(df))
    # add_to_cart 6/20 = 30%, checkout 5/6, shipping 5/5, payment 1/5 = 20%, purchase 1/1
    assert weakest["label"] == "Thông tin thanh toán"
    assert weakest["drop_rate"] == pytest.approx(0.8)


def test_tracked_days_only_drops_untracked(sessions):
    out = funnel.tracked_days_only(sessions)
    assert out["is_add_to_cart_tracked"].all()
    assert len(out) < len(sessions)


def test_step_rates_by_skips_small_segments():
    df = _frame(*_sessions_with(120, has_view_item=1, has_add_to_cart=1, channel_group="Direct"),
                *_sessions_with(30, has_view_item=1, channel_group="Email"))
    rates = funnel.step_rates_by(df, "channel_group", min_sessions=100)
    assert list(rates.index) == ["Direct"]
    assert rates.loc["Direct", "Thêm vào giỏ"] == pytest.approx(1.0)


def test_product_stage_table_ratio_only_checkout_to_purchase():
    table = funnel.product_stage_table(load_products(MOCK))
    assert "units_per_checkout" in table.columns
    assert table["item_revenue_usd"].is_monotonic_decreasing


# ---------- compare ----------

def test_compare_groups_ranks_small_samples_last():
    df = _frame(*_sessions_with(200, channel_group="Direct", has_purchase=1, order_count=1,
                                revenue_usd=10.0),
                *_sessions_with(5, channel_group="Email", has_purchase=1, order_count=1,
                                revenue_usd=500.0))
    table = compare.compare_groups(df, "channel_group", ["Direct", "Email"], "revenue_per_session_usd")
    assert list(table["channel_group"]) == ["Direct", "Email"]
    assert list(table["rank"]) == [1, 2]
    assert list(table["small_sample"]) == [False, True]


def test_default_periods_use_previous_period_when_available():
    a, b = compare.default_periods(pd.Timestamp("2020-12-01"), pd.Timestamp("2020-12-31"),
                                   pd.Timestamp("2020-11-01"))
    assert a == (pd.Timestamp("2020-11-01"), pd.Timestamp("2020-11-30"))
    assert b == (pd.Timestamp("2020-12-01"), pd.Timestamp("2020-12-31"))


def test_default_periods_split_range_when_previous_is_out_of_data():
    a, b = compare.default_periods(pd.Timestamp("2020-11-01"), pd.Timestamp("2021-01-31"),
                                   pd.Timestamp("2020-11-01"))
    assert a[0] == pd.Timestamp("2020-11-01") and b[1] == pd.Timestamp("2021-01-31")
    assert b[0] == a[1] + pd.Timedelta(days=1)


def test_compare_periods_applies_dimension_filters(sessions):
    f = Filters(pd.Timestamp("2020-11-01"), pd.Timestamp("2021-01-31"), channels=("Direct",))
    a = (pd.Timestamp("2020-11-01"), pd.Timestamp("2020-11-30"))
    b = (pd.Timestamp("2020-12-01"), pd.Timestamp("2020-12-31"))
    table = compare.compare_periods(sessions, f, a, b)
    direct_dec = sessions[(sessions["channel_group"] == "Direct")
                          & sessions["session_date"].between(*b)]
    assert table.loc["sessions", "b"] == len(direct_dec)
    assert table.loc["sessions", "change"] == pytest.approx(
        table.loc["sessions", "b"] / table.loc["sessions", "a"] - 1)


def test_aligned_daily_numbers_days_from_one(sessions):
    f = Filters(pd.Timestamp("2020-11-01"), pd.Timestamp("2021-01-31"))
    a = (pd.Timestamp("2020-11-01"), pd.Timestamp("2020-11-07"))
    b = (pd.Timestamp("2020-12-01"), pd.Timestamp("2020-12-07"))
    daily = compare.aligned_daily(sessions, f, a, b, "sessions")
    assert sorted(daily["day"].unique()) == list(range(1, 8))
    assert set(daily["period"]) == {"Kỳ A", "Kỳ B"}


# ---------- channel quality ----------

def test_classify_assigns_quadrants():
    rows = (
        _sessions_with(400, channel_group="Big good", has_purchase=1, order_count=1)
        + _sessions_with(600, channel_group="Big good")
        + _sessions_with(1000, channel_group="Big bad")
        + _sessions_with(200, channel_group="Small good", has_purchase=1, order_count=1)
        + _sessions_with(200, channel_group="Small bad")
        + _sessions_with(10, channel_group="Tiny")
    )
    table, volume_cut, quality_cut = cq.classify(_frame(*rows), "channel_group", "conversion_rate")
    quadrant = table.set_index("channel_group")["quadrant"]
    assert quadrant["Big good"] == cq.CORE
    assert quadrant["Big bad"] == cq.LEAKY
    assert quadrant["Small good"] == cq.NICHE
    assert quadrant["Small bad"] == cq.WEAK
    assert quadrant["Tiny"] == cq.SMALL
    assert volume_cut == pytest.approx(600)          # median of 1000, 1000, 200, 200
    assert quality_cut == pytest.approx(600 / 2410)  # filtered overall: 40% vs 100% vs 0%
    assert table["session_share"].sum() == pytest.approx(1.0)


def test_drop_rate_is_never_negative():
    # One session reaches shipping info without begin_checkout (unordered counting)
    df = _frame(*_sessions_with(2, has_view_item=1, has_add_to_cart=1, has_begin_checkout=1,
                                has_add_shipping_info=1),
                {"has_view_item": 1, "has_add_to_cart": 1, "has_add_shipping_info": 1})
    table = funnel.funnel_table(df).set_index("label")
    assert table.loc["Thông tin giao hàng", "step_rate"] == pytest.approx(3 / 2)
    assert table.loc["Thông tin giao hàng", "drop_rate"] == 0.0


@pytest.mark.parametrize("start, end, has_note", [
    ("2020-11-01", "2020-11-30", True),
    ("2020-11-10", "2020-11-10", True),
    ("2020-11-11", "2021-01-31", False),
    ("2020-10-01", "2020-10-31", False),
])
def test_no_valid_order_note(start, end, has_note):
    note = kpi.no_valid_order_note(pd.Timestamp(start), pd.Timestamp(end))
    assert (note is not None) == has_note


# ---------- drill-down ----------

from src.dashboard.analysis import drilldown as dd  # noqa: E402

CHANNEL_H, TIME_H, PRODUCT_H = dd.HIERARCHIES


def test_drill_levels_partition_the_parent(sessions):
    top = dd.level_table(sessions, CHANNEL_H, ())
    assert top["sessions"].sum() == len(sessions)
    channel = top.loc[0, "key"]
    children = dd.level_table(sessions, CHANNEL_H, (channel,))
    assert children["sessions"].sum() == (sessions["channel_group"] == channel).sum()
    assert children["revenue_share_total"].sum() == pytest.approx(1.0)


def test_drill_path_filters_every_level(sessions):
    channel = sessions["channel_group"].iloc[0]
    source = sessions.loc[sessions["channel_group"] == channel, "source_medium"].iloc[0]
    rows = dd.subset(sessions, CHANNEL_H, (channel, source))
    assert set(rows["channel_group"]) == {channel}
    assert set(rows["source_medium"]) == {source}
    table = dd.level_table(sessions, CHANNEL_H, (channel, source))
    assert table["sessions"].sum() == len(rows)


def test_time_hierarchy_is_chronological_and_nested(sessions):
    df = dd.prepare(sessions, TIME_H)
    months = dd.level_table(df, TIME_H, ())
    assert list(months["key"]) == sorted(months["key"])
    assert len(months) == 3
    nov = pd.Timestamp("2020-11-01")
    weeks = dd.level_table(df, TIME_H, (nov,))
    assert (weeks["key"].dt.day_of_week == 0).all()        # weeks start on Monday
    week = weeks.loc[1, "key"]
    days = dd.level_table(df, TIME_H, (nov, week))
    assert len(days) <= 7
    assert days["key"].between(week, week + pd.Timedelta(days=6)).all()


def test_product_hierarchy_sums_measures():
    products = load_products(MOCK)
    top = dd.level_table(products, PRODUCT_H, ())
    assert top["item_revenue_usd"].sum() == pytest.approx(products["item_revenue_usd"].sum())
    assert top["item_revenue_usd"].is_monotonic_decreasing
    assert top["revenue_share"].sum() == pytest.approx(1.0)


def test_can_drill_stops_at_the_last_level():
    assert dd.can_drill(CHANNEL_H, ())
    assert dd.can_drill(CHANNEL_H, ("Direct",))
    assert not dd.can_drill(CHANNEL_H, ("Direct", "(direct) / (none)"))
    assert dd.can_drill(PRODUCT_H, ())
    assert not dd.can_drill(PRODUCT_H, ("Apparel",))


def test_path_deeper_than_hierarchy_is_rejected(sessions):
    with pytest.raises(ValueError):
        dd.subset(sessions, PRODUCT_H, ("a", "b", "c"))


def test_format_key_time_levels():
    month, week, day = TIME_H.levels
    assert dd.format_key(pd.Timestamp("2020-12-01"), month) == "Tháng 12/2020"
    assert dd.format_key(pd.Timestamp("2020-11-30"), week) == "Tuần 30/11 – 06/12/2020"
    assert dd.format_key(pd.Timestamp("2020-12-05"), day) == "05/12/2020"
