"""Feature 3 — Performance comparison: groups side by side with a ranking,
or the same slice over two periods."""

import pandas as pd
import plotly.express as px
import streamlit as st

from src.dashboard import kpi
from src.dashboard.analysis import compare
from src.dashboard.config import DIMENSIONS
from src.dashboard.context import PageContext
from src.dashboard.formatting import (PRIMARY, SERIES, fmt_delta, fmt_value,
                                      kpi_display_table, style_figure)

MIN_SESSIONS = 100
DEFAULT_GROUPS = 5


def _render_groups(ctx: PageContext) -> None:
    df = ctx.filtered
    left, mid, right = st.columns([1, 2, 1])
    dim_label = left.selectbox("So sánh theo", list(DIMENSIONS), key="cmp_dim")
    by = DIMENSIONS[dim_label]
    options = df[by].value_counts().index.tolist()
    groups = mid.multiselect(dim_label, options, default=options[:DEFAULT_GROUPS],
                             key=f"cmp_groups_{by}",
                             placeholder=f"Chọn {dim_label.lower()} để so sánh")
    rank_by = right.selectbox("Xếp hạng theo", compare.RANK_KPIS, format_func=kpi.label,
                              key="cmp_rank")
    if not groups:
        st.info(f"Chọn ít nhất một {dim_label.lower()} để so sánh.")
        return

    table = compare.compare_groups(df, by, groups, rank_by, MIN_SESSIONS)
    bars = table.iloc[::-1]
    fig = px.bar(bars, x=rank_by, y=by, orientation="h",
                 text=bars[rank_by].map(lambda v: fmt_value(v, kpi.unit(rank_by))))
    fig.update_traces(marker_color=PRIMARY, textposition="outside", cliponaxis=False,
                      hovertemplate="%{y}: %{text}<extra></extra>")
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(range=[0, bars[rank_by].max() * 1.18])  # room for value labels
    if kpi.unit(rank_by) == "%":
        fig.update_xaxes(tickformat=".1%")
    st.markdown(f"**Xếp hạng theo {kpi.label(rank_by).lower()}**")
    st.plotly_chart(style_figure(fig, height=60 + 34 * len(bars)), width="stretch")

    table["note"] = table["small_sample"].map({True: f"Dưới {MIN_SESSIONS} phiên", False: ""})
    shown = kpi_display_table(table, by, dim_label, compare.COMPARE_KPIS,
                              extra={"note": "Ghi chú"})
    shown.insert(0, "Hạng", table["rank"])
    st.dataframe(shown, hide_index=True, width="stretch")
    if table["small_sample"].any():
        st.caption(f"Nhóm dưới {MIN_SESSIONS} phiên được xếp sau cùng: tỷ lệ của chúng "
                   "dao động mạnh theo vài phiên.")


def _period_input(label: str, default, key: str, bounds):
    picked = st.date_input(label, value=(default[0].date(), default[1].date()),
                           min_value=bounds[0], max_value=bounds[1], format="DD/MM/YYYY", key=key)
    if isinstance(picked, tuple) and len(picked) == 2:
        return pd.Timestamp(picked[0]), pd.Timestamp(picked[1])
    return default


def _render_periods(ctx: PageContext) -> None:
    sessions, f = ctx.sessions, ctx.filters
    data_start = sessions["session_date"].min()
    bounds = (data_start.date(), sessions["session_date"].max().date())
    default_a, default_b = compare.default_periods(f.start, f.end, data_start)

    left, right = st.columns(2)
    with left:
        a = _period_input("Kỳ A", default_a, "cmp_period_a", bounds)
    with right:
        b = _period_input("Kỳ B", default_b, "cmp_period_b", bounds)
    st.caption("Bộ lọc kênh, thiết bị, quốc gia, loại người dùng ở thanh bên áp dụng cho cả hai kỳ; "
               "khoảng thời gian ở thanh bên được thay bằng Kỳ A và Kỳ B.")

    notes = {kpi.data_gap_note(*a), kpi.data_gap_note(*b)} - {None}
    for note in notes:
        st.warning(note, icon=":material/info:")

    table = compare.compare_periods(sessions, f, a, b)
    cols = st.columns(4)
    for col, kpi_id in zip(cols * 2, compare.COMPARE_KPIS):
        row = table.loc[kpi_id]
        col.metric(kpi.label(kpi_id), fmt_value(row["b"], kpi.unit(kpi_id)),
                   delta=fmt_delta(row["change"]), border=True,
                   help=f"Kỳ A: {fmt_value(row['a'], kpi.unit(kpi_id))}")

    kpi_id = st.selectbox("Diễn biến theo ngày", compare.COMPARE_KPIS,
                          index=compare.COMPARE_KPIS.index("revenue_usd"),
                          format_func=kpi.label, key="cmp_period_kpi")
    daily = compare.aligned_daily(sessions, f, a, b, kpi_id)
    fig = px.line(daily, x="day", y="value", color="period",
                  color_discrete_map={"Kỳ A": SERIES[1], "Kỳ B": SERIES[0]},
                  custom_data=["date"])
    fig.update_traces(line=dict(width=2),
                      hovertemplate="%{customdata[0]|%d/%m/%Y}: %{y}<extra>%{fullData.name}</extra>")
    fig.update_layout(showlegend=True, legend=dict(title=None, orientation="h", y=1.08, x=0))
    fig = style_figure(fig)
    fig.update_layout(showlegend=True)
    fig.update_xaxes(title="Ngày thứ")
    if kpi.unit(kpi_id) == "%":
        fig.update_yaxes(tickformat=".1%")
    st.plotly_chart(fig, width="stretch")


def render(ctx: PageContext) -> None:
    """Draw the comparison page."""
    st.title("So sánh hiệu suất")
    if ctx.filtered.empty:
        st.warning("Không có phiên nào khớp bộ lọc hiện tại.")
        return
    groups, periods = st.tabs(["So sánh nhóm", "So sánh hai kỳ"])
    with groups:
        _render_groups(ctx)
    with periods:
        _render_periods(ctx)
