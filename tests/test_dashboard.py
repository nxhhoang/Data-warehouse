"""Unit tests for the dashboard data layer, filters and KPI formulas.

No Streamlit and no GCP needed: they exercise the pure-pandas modules on the
mock source and on small hand-built frames.
Run from the repository root:  pytest tests/test_dashboard.py
"""

import math

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("yaml")

from src.dashboard import kpi  # noqa: E402
from src.dashboard.config import CHANNEL_GROUPS, Settings  # noqa: E402
from src.dashboard.data import (PRODUCT_COLUMNS, SESSION_COLUMNS,  # noqa: E402
                                coerce, load_products, load_sessions)
from src.dashboard.filters import Filters, apply_filters, apply_product_filters  # noqa: E402
from src.dashboard.formatting import fmt_delta, fmt_value  # noqa: E402
from src.dashboard.mock import make_sessions, untracked_add_to_cart_days  # noqa: E402

MOCK = Settings("mock", "", 0.2)


@pytest.fixture(scope="module")
def sessions():
    return load_sessions(MOCK)


def _session(**overrides):
    """One session row with every measure at zero."""
    row = {c: 0 for c in SESSION_COLUMNS}
    row.update(session_id="s", user_key=1, session_date="2020-11-02",
               is_weekend=False, is_holiday_season=False, is_add_to_cart_tracked=True,
               is_new_user=False, revenue_usd=0.0)
    for col in ("channel_group", "source", "medium", "campaign", "attribution_basis",
                "device_category", "operating_system", "continent", "country",
                "landing_page_type"):
        row[col] = "Unknown"
    row.update(overrides)
    return row


def _frame(*rows):
    return coerce(pd.DataFrame(rows), SESSION_COLUMNS)


# ---------- data layer ----------

def test_mock_sessions_match_schema(sessions):
    assert list(sessions.columns) == list(SESSION_COLUMNS)
    assert sessions["session_id"].is_unique
    assert set(sessions["channel_group"]) <= set(CHANNEL_GROUPS)
    assert sessions["session_date"].min() == pd.Timestamp("2020-11-01")
    assert sessions["session_date"].max() == pd.Timestamp("2021-01-31")


def test_mock_products_match_schema():
    products = load_products(MOCK)
    assert list(products.columns) == list(PRODUCT_COLUMNS)
    assert (products["units_sold"] <= products["item_checkout_events"]).all()


def test_mock_new_user_session_is_the_users_first(sessions):
    new = sessions[sessions["is_new_user_session"] == 1]
    assert (new["user_session_number"] == 1).all()
    assert new["is_new_user"].all()
    # At most one new-user session per user
    assert new["user_key"].is_unique
    assert (sessions["user_session_number"] >= 1).all()


def test_mock_products_cover_channels_and_devices():
    products = load_products(MOCK)
    assert set(products["channel_group"]) <= set(CHANNEL_GROUPS)
    assert products["device_category"].nunique() > 1


def test_mock_new_user_session_is_the_users_first(sessions):
    new = sessions[sessions["is_new_user_session"] == 1]
    assert (new["user_session_number"] == 1).all()
    assert new["is_new_user"].all()
    # At most one new-user session per user
    assert new["user_key"].is_unique
    assert (sessions["user_session_number"] >= 1).all()


def test_mock_products_cover_channels_and_devices():
    products = load_products(MOCK)
    assert set(products["channel_group"]) <= set(CHANNEL_GROUPS)
    assert products["device_category"].nunique() > 1


def test_mock_is_deterministic():
    a, b = make_sessions(1_000), make_sessions(1_000)
    pd.testing.assert_frame_equal(a, b)


def test_mock_has_no_add_to_cart_on_untracked_days(sessions):
    untracked = sessions["session_date"].isin(untracked_add_to_cart_days())
    assert len(untracked_add_to_cart_days()) == 18
    assert sessions.loc[untracked, "has_add_to_cart"].sum() == 0
    assert not sessions.loc[untracked, "is_add_to_cart_tracked"].any()


def test_mock_funnel_flags_are_consistent(sessions):
    # A session that paid must have checked out; purchases need payment info
    assert (sessions["has_add_payment_info"] <= sessions["has_begin_checkout"]).all()
    assert (sessions["has_purchase"] <= sessions["has_add_payment_info"]).all()
    assert ((sessions["order_count"] > 0) == (sessions["has_purchase"] == 1)).all()


def test_coerce_fills_nulls_and_rejects_missing_columns():
    df = _frame(_session(country=None, revenue_usd=None))
    assert df.loc[0, "country"] == "Unknown"
    assert df.loc[0, "revenue_usd"] == 0.0
    with pytest.raises(KeyError):
        coerce(pd.DataFrame({"session_id": ["x"]}), SESSION_COLUMNS)


# ---------- KPI formulas (kpi_dictionary.yaml) ----------

def test_every_summarized_kpi_is_in_the_dictionary(sessions):
    assert set(kpi.summarize(sessions)) <= set(kpi.kpi_dictionary())


def test_ratios_are_recomputed_from_numerators():
    df = _frame(
        _session(session_id="a", user_key=1, has_purchase=1, order_count=1, revenue_usd=100.0),
        _session(session_id="b", user_key=1, has_purchase=1, order_count=2, revenue_usd=50.0),
        _session(session_id="c", user_key=2),
        _session(session_id="d", user_key=3),
    )
    s = kpi.summarize(df)
    assert s["sessions"] == 4 and s["users"] == 3
    assert s["conversion_rate"] == pytest.approx(2 / 4)
    assert s["aov_usd"] == pytest.approx(150 / 3)      # revenue / orders, not mean of AOVs
    assert s["revenue_per_user_usd"] == pytest.approx(150 / 3)
    assert s["sessions_per_user"] == pytest.approx(4 / 3)


def test_funnel_rates_follow_dictionary_numerators():
    df = _frame(
        _session(session_id="a", has_view_item=1, has_add_to_cart=1, has_begin_checkout=1,
                 has_add_shipping_info=1, has_add_payment_info=1, has_purchase=1, order_count=1),
        _session(session_id="b", has_view_item=1, has_add_to_cart=1),
        # Purchase without add_to_cart / payment info must not count as completion
        _session(session_id="c", has_view_item=1, has_purchase=1, order_count=1),
        _session(session_id="d", has_view_item=1),
    )
    s = kpi.summarize(df)
    assert s["add_to_cart_rate"] == pytest.approx(2 / 4)
    assert s["begin_checkout_rate"] == pytest.approx(1 / 2)
    assert s["purchase_completion_rate"] == pytest.approx(1 / 1)
    assert s["cart_abandonment_rate"] == pytest.approx(1 - 1 / 2)


def test_undefined_ratios_are_nan():
    s = kpi.summarize(_frame(_session()))
    assert math.isnan(s["aov_usd"])
    assert math.isnan(s["add_to_cart_rate"])


def test_new_user_rate_counts_distinct_users():
    df = _frame(
        _session(session_id="a", user_key=1, is_new_user=True),
        _session(session_id="b", user_key=1, is_new_user=True),
        _session(session_id="c", user_key=2),
    )
    assert kpi.summarize(df)["new_user_rate"] == pytest.approx(1 / 2)


def test_breakdown_share_is_relative_to_filtered_total(sessions):
    table = kpi.breakdown(sessions, "channel_group")
    assert table["revenue_share_total"].sum() == pytest.approx(1.0)
    assert table["sessions"].sum() == len(sessions)


def test_daily_series_leaves_untracked_days_empty(sessions):
    series = kpi.time_series(sessions, "add_to_cart_rate", "Ngày")
    untracked = series["period"].isin(untracked_add_to_cart_days())
    assert series.loc[untracked, "value"].isna().all()
    assert series.loc[~untracked, "value"].notna().all()


def test_monthly_series_sums_back_to_total(sessions):
    series = kpi.time_series(sessions, "revenue_usd", "Tháng")
    assert len(series) == 3
    assert series["value"].sum() == pytest.approx(sessions["revenue_usd"].sum())


def test_previous_period_has_same_length():
    start, end = pd.Timestamp("2020-12-10"), pd.Timestamp("2020-12-16")
    assert kpi.previous_period(start, end) == (pd.Timestamp("2020-12-03"),
                                               pd.Timestamp("2020-12-09"))


@pytest.mark.parametrize("start, end, expected", [
    ("2020-12-01", "2020-12-31", ("2020-11-01", "2020-11-30")),
    ("2021-01-01", "2021-01-31", ("2020-12-01", "2020-12-31")),
    ("2020-12-01", "2021-01-31", ("2020-10-01", "2020-11-30")),
])
def test_previous_period_of_whole_months_is_calendar_months(start, end, expected):
    got = kpi.previous_period(pd.Timestamp(start), pd.Timestamp(end))
    assert got == (pd.Timestamp(expected[0]), pd.Timestamp(expected[1]))


def test_relative_change():
    assert kpi.relative_change(120, 100) == pytest.approx(0.2)
    assert math.isnan(kpi.relative_change(1, 0))
    assert math.isnan(kpi.relative_change(1, None))


# ---------- filters ----------

def test_filters_combine_with_and(sessions):
    f = Filters(pd.Timestamp("2020-12-01"), pd.Timestamp("2020-12-07"),
                channels=("Direct", "Referral"), devices=("mobile",),
                user_type="Người dùng mới")
    out = apply_filters(sessions, f)
    assert not out.empty
    assert out["session_date"].between(f.start, f.end).all()
    assert set(out["channel_group"]) <= {"Direct", "Referral"}
    assert set(out["device_category"]) == {"mobile"}
    assert (out["is_new_user_session"] == 1).all()


def test_returning_filter_excludes_new_user_sessions(sessions):
    f = Filters(sessions["session_date"].min(), sessions["session_date"].max(),
                user_type="Người dùng cũ")
    out = apply_filters(sessions, f)
    assert (out["is_new_user_session"] == 0).all()
    assert len(out) + (sessions["is_new_user_session"] == 1).sum() == len(sessions)


def test_product_filters_apply_date_channel_device():
    products = load_products(MOCK)
    f = Filters(pd.Timestamp("2020-12-01"), pd.Timestamp("2020-12-07"),
                channels=("Direct",), devices=("mobile",), countries=("Vietnam",))
    out = apply_product_filters(products, f)
    assert not out.empty
    assert set(out["channel_group"]) == {"Direct"}
    assert set(out["device_category"]) == {"mobile"}
    assert out["date"].between(f.start, f.end).all()


def test_returning_filter_excludes_new_user_sessions(sessions):
    f = Filters(sessions["session_date"].min(), sessions["session_date"].max(),
                user_type="Người dùng cũ")
    out = apply_filters(sessions, f)
    assert (out["is_new_user_session"] == 0).all()
    assert len(out) + (sessions["is_new_user_session"] == 1).sum() == len(sessions)


def test_product_filters_apply_date_channel_device():
    products = load_products(MOCK)
    f = Filters(pd.Timestamp("2020-12-01"), pd.Timestamp("2020-12-07"),
                channels=("Direct",), devices=("mobile",), countries=("Vietnam",))
    out = apply_product_filters(products, f)
    assert not out.empty
    assert set(out["channel_group"]) == {"Direct"}
    assert set(out["device_category"]) == {"mobile"}
    assert out["date"].between(f.start, f.end).all()


def test_empty_filter_keeps_everything_in_range(sessions):
    f = Filters(sessions["session_date"].min(), sessions["session_date"].max())
    assert len(apply_filters(sessions, f)) == len(sessions)


# ---------- formatting ----------

@pytest.mark.parametrize("value, unit, expected", [
    (0.01234, "%", "1,23%"),
    (1234567.891, "USD", "$1.234.567,89"),
    (360000, "phiên", "360.000"),
    (1.5, "phiên/người dùng", "1,50"),
    (float("nan"), "%", "—"),
])
def test_fmt_value(value, unit, expected):
    assert fmt_value(value, unit) == expected


def test_fmt_delta():
    assert fmt_delta(0.125) == "+12,5%"
    assert fmt_delta(-0.05) == "-5,0%"
    assert fmt_delta(float("nan")) is None
