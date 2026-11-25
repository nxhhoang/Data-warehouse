"""Multi-dimensional filters (feature 2): one filter state shared by all pages.

``apply_filters`` is pure pandas so it can be unit tested; ``render_sidebar``
draws the Streamlit widgets and returns the chosen state.
"""

from dataclasses import dataclass, field

import pandas as pd

from src.dashboard.config import CHANNEL_GROUPS, DEVICE_CATEGORIES

USER_TYPES = ("Tất cả", "Người dùng mới", "Người dùng cũ")


@dataclass(frozen=True)
class Filters:
    """Chosen filter values. An empty tuple means "no filter on this column"."""

    start: pd.Timestamp
    end: pd.Timestamp
    channels: tuple[str, ...] = field(default_factory=tuple)
    devices: tuple[str, ...] = field(default_factory=tuple)
    countries: tuple[str, ...] = field(default_factory=tuple)
    user_type: str = USER_TYPES[0]

    def with_dates(self, start: pd.Timestamp, end: pd.Timestamp) -> "Filters":
        """Same dimension filters over another date range (period comparison)."""
        return Filters(start, end, self.channels, self.devices, self.countries, self.user_type)


def apply_filters(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    """Rows of the session frame that match every active filter."""
    mask = df["session_date"].between(f.start, f.end)
    if f.channels:
        mask &= df["channel_group"].isin(f.channels)
    if f.devices:
        mask &= df["device_category"].isin(f.devices)
    if f.countries:
        mask &= df["country"].isin(f.countries)
    if f.user_type == USER_TYPES[1]:
        mask &= df["is_new_user_session"] == 1
    elif f.user_type == USER_TYPES[2]:
        mask &= df["is_new_user_session"] == 0
    return df.loc[mask]


def apply_product_filters(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    """Rows of the product frame matching the date, channel and device filters.

    The product mart has no country or user-type dimension, so those two
    filters do not apply to product figures.
    """
    mask = df["date"].between(f.start, f.end)
    if f.channels:
        mask &= df["channel_group"].isin(f.channels)
    if f.devices:
        mask &= df["device_category"].isin(f.devices)
    return df.loc[mask]


def _ordered(values: pd.Series, preferred: tuple[str, ...]) -> list[str]:
    """Known values in the preferred order, then any other value alphabetically."""
    present = set(values.dropna().unique())
    known = [v for v in preferred if v in present]
    return known + sorted(present - set(known))


def render_sidebar(df: pd.DataFrame) -> Filters:
    """Draw the filter widgets in the sidebar and return the chosen Filters."""
    import streamlit as st

    min_date = df["session_date"].min().date()
    max_date = df["session_date"].max().date()

    st.sidebar.header("Bộ lọc", help="Chức năng 2: áp dụng cho mọi trang.")
    picked = st.sidebar.date_input(
        "Khoảng thời gian", value=(min_date, max_date),
        min_value=min_date, max_value=max_date, format="DD/MM/YYYY", key="f_dates",
    )
    # While the user is picking, date_input returns a single date
    start, end = (picked if isinstance(picked, tuple) and len(picked) == 2
                  else (min_date, max_date))

    channels = st.sidebar.multiselect(
        "Kênh", _ordered(df["channel_group"], CHANNEL_GROUPS),
        placeholder="Tất cả kênh", key="f_channels",
    )
    devices = st.sidebar.multiselect(
        "Thiết bị", _ordered(df["device_category"], DEVICE_CATEGORIES),
        placeholder="Tất cả thiết bị", key="f_devices",
    )
    countries = st.sidebar.multiselect(
        "Quốc gia", df["country"].value_counts().index.tolist(),
        placeholder="Tất cả quốc gia", key="f_countries",
    )
    user_type = st.sidebar.radio("Loại người dùng", USER_TYPES, key="f_user_type")

    return Filters(
        start=pd.Timestamp(start), end=pd.Timestamp(end),
        channels=tuple(channels), devices=tuple(devices),
        countries=tuple(countries), user_type=user_type,
    )
