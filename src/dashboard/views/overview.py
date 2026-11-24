"""Feature 1 — Executive overview: headline KPIs vs the previous period,
trend by day/week/month, and the breakdown by channel."""

import plotly.express as px
import streamlit as st

from src.dashboard import kpi
from src.dashboard.context import PageContext
from src.dashboard.filters import apply_filters
from src.dashboard.formatting import (PRIMARY, fmt_delta, fmt_value, kpi_display_table,
                                      style_figure)

HEADLINE_KPIS = ("sessions", "users", "conversion_rate", "orders", "revenue_usd", "aov_usd")
TABLE_KPIS = ("sessions", "users", "conversion_rate", "orders", "revenue_usd",
              "revenue_per_session_usd", "revenue_share_total")


_label, _unit = kpi.label, kpi.unit


def _render_headline(ctx: PageContext, current: dict) -> None:
    f = ctx.filters
    prev_start, prev_end = kpi.previous_period(f.start, f.end)
    has_previous = prev_start >= ctx.sessions["session_date"].min()
    previous = (kpi.summarize(apply_filters(ctx.sessions, f.with_dates(prev_start, prev_end)))
                if has_previous else {})

    # Two rows of three: six tiles in one row truncate USD values
    cols = [*st.columns(3), *st.columns(3)]
    for col, kpi_id in zip(cols, HEADLINE_KPIS):
        change = kpi.relative_change(current[kpi_id], previous.get(kpi_id))
        col.metric(
            _label(kpi_id), fmt_value(current[kpi_id], _unit(kpi_id)),
            delta=fmt_delta(change), border=True,
            help=kpi.kpi_dictionary()[kpi_id]["formula_text"],
        )
        # Feature 10: jump to the traceability page with this KPI selected
        trace_page = ctx.pages.get("truy-vet")
        if trace_page and col.button("Truy vết", key=f"ov_trace_{kpi_id}", type="tertiary",
                                     icon=":material/manage_search:"):
            st.session_state["trace_kpi"] = kpi_id
            st.switch_page(trace_page)
    if has_previous:
        st.caption(f"So với kỳ trước: {prev_start:%d/%m/%Y} – {prev_end:%d/%m/%Y}")
    else:
        st.caption("Không có kỳ trước cùng độ dài trong dữ liệu (bắt đầu 01/11/2020), "
                   "nên không hiển thị mức thay đổi.")


def _render_trend(df) -> None:
    left, right = st.columns([3, 1])
    options = list(kpi.summarize(df.head(0)).keys())
    kpi_id = left.selectbox("Chỉ số", options, index=options.index("revenue_usd"),
                            format_func=_label, key="ov_trend_kpi")
    grain = right.segmented_control("Theo", list(kpi.GRAINS), default="Ngày",
                                    key="ov_trend_grain") or "Ngày"

    series = kpi.time_series(df, kpi_id, grain)
    fig = px.line(series, x="period", y="value", markers=grain != "Ngày")
    fig.update_traces(line=dict(color=PRIMARY, width=2), connectgaps=False,
                      hovertemplate="%{y}<extra></extra>", name=_label(kpi_id))
    fig.update_xaxes(tickformat="%d/%m/%Y" if grain == "Tháng" else "%d/%m",
                     hoverformat="%d/%m/%Y")
    if _unit(kpi_id) == "%":
        fig.update_yaxes(tickformat=".1%")
    st.plotly_chart(style_figure(fig), width="stretch")
    note = kpi.data_gap_note(df["session_date"].min(), df["session_date"].max())
    if note and kpi_id in kpi.ORDER_KPIS:
        st.caption(note)
    if kpi_id in kpi.CART_DEPENDENT:
        st.caption("add_to_cart không được ghi nhận trong 18/92 ngày; các ngày đó để trống, "
                   "không nội suy.")


def _render_channels(df) -> None:
    table = kpi.breakdown(df, "channel_group")
    bars = table.sort_values("revenue_usd")
    fig = px.bar(bars, x="revenue_usd", y="channel_group", orientation="h")
    fig.update_traces(marker_color=PRIMARY, hovertemplate="%{y}: $%{x:,.2f}<extra></extra>")
    st.markdown(f"**{_label('revenue_usd')} theo kênh**")
    st.plotly_chart(style_figure(fig, height=40 + 32 * len(bars)), width="stretch")

    st.dataframe(kpi_display_table(table, "channel_group", "Kênh", TABLE_KPIS),
                 hide_index=True, width="stretch")


def render(ctx: PageContext) -> None:
    """Draw the overview page."""
    st.title("Tổng quan điều hành")
    df = ctx.filtered
    if df.empty:
        st.warning("Không có phiên nào khớp bộ lọc hiện tại.")
        return

    _render_headline(ctx, kpi.summarize(df))
    st.subheader("Xu hướng")
    _render_trend(df)
    st.subheader("Hiệu suất theo kênh")
    _render_channels(df)
