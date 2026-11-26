"""Multi-dimensional filters (feature 2): one filter state shared by all pages.

``apply_filters`` is pure pandas so it can be unit tested; ``render_sidebar``
draws the Streamlit widgets and returns the chosen state.
"""

from dataclasses import dataclass, field, replace

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
    source_mediums: tuple[str, ...] = field(default_factory=tuple)
    campaigns: tuple[str, ...] = field(default_factory=tuple)
    product_categories: tuple[str, ...] = field(default_factory=tuple)

    def with_dates(self, start: pd.Timestamp, end: pd.Timestamp) -> "Filters":
        """Preserve every dimension while changing the comparison date range."""
        return replace(self, start=start, end=end)


def apply_filters(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    """Rows of the session frame that match every active filter."""
    mask = df["session_date"].between(f.start, f.end)
    if f.channels:
        mask &= df["channel_group"].isin(f.channels)
    if f.devices:
        mask &= df["device_category"].isin(f.devices)
    if f.countries:
        mask &= df["country"].isin(f.countries)
    if f.source_mediums:
        mask &= df["source_medium"].isin(f.source_mediums)
    if f.campaigns:
        mask &= df["campaign"].isin(f.campaigns)
    if f.user_type == USER_TYPES[1]:
        mask &= df["is_new_user_session"] == 1
    elif f.user_type == USER_TYPES[2]:
        mask &= df["is_new_user_session"] == 0
    return df.loc[mask]


def apply_product_filters(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    """Filter product rows on dimensions actually present in the product frame.

    Product rows have source/medium, campaign and item category through their
    conformed dimensions. Country and user type belong to session data, so
    those filters intentionally do not apply here.
    """
    mask = df["date"].between(f.start, f.end)
    if f.channels:
        mask &= df["channel_group"].isin(f.channels)
    if f.devices:
        mask &= df["device_category"].isin(f.devices)
    if f.source_mediums:
        mask &= df["source_medium"].isin(f.source_mediums)
    if f.campaigns:
        mask &= df["campaign"].isin(f.campaigns)
    if f.product_categories:
        mask &= df["item_category"].isin(f.product_categories)
    return df.loc[mask]


def _ordered(values: pd.Series, preferred: tuple[str, ...]) -> list[str]:
    """Known values in the preferred order, then any other value alphabetically."""
    present = set(values.dropna().unique())
    known = [v for v in preferred if v in present]
    return known + sorted(present - set(known))


def render_sidebar(df: pd.DataFrame, products: pd.DataFrame,
                   resume_filters: "Filters | None" = None) -> Filters:
    """Draw shared filters and restore a saved set after a role switch."""
    import streamlit as st

    min_date = df["session_date"].min().date()
    max_date = df["session_date"].max().date()

    if resume_filters is not None:
        saved_start = min(max(resume_filters.start.date(), min_date), max_date)
        saved_end = min(max(resume_filters.end.date(), min_date), max_date)
        st.session_state["f_dates"] = (saved_start, saved_end)
        field_options = {
            "f_channels": (resume_filters.channels, df["channel_group"]),
            "f_devices": (resume_filters.devices, df["device_category"]),
            "f_countries": (resume_filters.countries, df["country"]),
            "f_source_mediums": (resume_filters.source_mediums, df["source_medium"]),
            "f_campaigns": (resume_filters.campaigns, df["campaign"]),
            "f_product_categories": (
                resume_filters.product_categories, products["item_category"]
            ),
        }
        for key, (saved, available) in field_options.items():
            valid_values = set(available.dropna())
            st.session_state[key] = [value for value in saved if value in valid_values]
        st.session_state["f_user_type"] = (
            resume_filters.user_type if resume_filters.user_type in USER_TYPES else USER_TYPES[0]
        )

    panel = st.sidebar.expander("Bộ lọc", expanded=False)
    panel.caption(
        "Các bộ lọc chỉ áp dụng khi dữ liệu có chiều tương ứng. Nhóm sản phẩm "
        "chỉ lọc số liệu sản phẩm; quốc gia và loại người dùng chỉ lọc KPI theo phiên."
    )
    picked = panel.date_input(
        "Khoảng thời gian", value=(min_date, max_date),
        min_value=min_date, max_value=max_date, format="DD/MM/YYYY", key="f_dates",
    )
    # While the user is picking, date_input returns a single date
    start, end = (picked if isinstance(picked, tuple) and len(picked) == 2
                  else (min_date, max_date))

    channels = panel.multiselect(
        "Kênh", _ordered(df["channel_group"], CHANNEL_GROUPS),
        placeholder="Tất cả kênh", key="f_channels",
    )
    devices = panel.multiselect(
        "Thiết bị", _ordered(df["device_category"], DEVICE_CATEGORIES),
        placeholder="Tất cả thiết bị", key="f_devices",
    )
    countries = panel.multiselect(
        "Quốc gia", df["country"].value_counts().index.tolist(),
        placeholder="Tất cả quốc gia", key="f_countries",
    )
    source_mediums = panel.multiselect(
        "Nguồn / medium", sorted(df["source_medium"].dropna().unique().tolist()),
        placeholder="Tất cả nguồn / medium", key="f_source_mediums",
    )
    campaigns = panel.multiselect(
        "Chiến dịch", sorted(df["campaign"].dropna().unique().tolist()),
        placeholder="Tất cả chiến dịch", key="f_campaigns",
    )
    product_categories = panel.multiselect(
        "Nhóm sản phẩm", sorted(products["item_category"].dropna().unique().tolist()),
        placeholder="Tất cả nhóm sản phẩm", key="f_product_categories",
    )
    user_type = panel.radio("Loại người dùng", USER_TYPES, key="f_user_type")

    return Filters(
        start=pd.Timestamp(start), end=pd.Timestamp(end),
        channels=tuple(channels), devices=tuple(devices),
        countries=tuple(countries), user_type=user_type,
        source_mediums=tuple(source_mediums), campaigns=tuple(campaigns),
        product_categories=tuple(product_categories),
    )
