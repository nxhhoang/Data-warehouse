"""Feature 9 — Scenario simulation: change each channel's traffic and conversion
rate, see the estimated orders and revenue against the historical baseline."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard import kpi
from src.dashboard.analysis import scenario as sc
from src.dashboard.context import PageContext
from src.dashboard.formatting import (NEUTRAL, SERIES, fmt_delta, fmt_signed_usd, fmt_value,
                                      style_figure)

BY = "channel_group"
TRAFFIC_COL = "Thay đổi lưu lượng (%)"
CR_COL = "Thay đổi tỷ lệ chuyển đổi (%)"


def _editor(base: pd.DataFrame) -> tuple[dict, dict]:
    version = st.session_state.setdefault("sc_version", 0)
    grid = pd.DataFrame({
        "Kênh": base[BY],
        "Số phiên": base["sessions"].map(lambda v: fmt_value(v, "phiên")),
        "Tỷ lệ chuyển đổi": base["conversion_rate"].map(lambda v: fmt_value(v, "%")),
        "Doanh thu": base["revenue_usd"].map(lambda v: fmt_value(v, "USD")),
        TRAFFIC_COL: 0, CR_COL: 0,
    })
    edited = st.data_editor(
        grid, hide_index=True, width="stretch", key=f"sc_editor_{version}",
        disabled=["Kênh", "Số phiên", "Tỷ lệ chuyển đổi", "Doanh thu"],
        column_config={
            TRAFFIC_COL: st.column_config.NumberColumn(min_value=-100, max_value=300, step=5,
                                                       format="%d%%"),
            CR_COL: st.column_config.NumberColumn(min_value=-100, max_value=300, step=5,
                                                  format="%d%%"),
        })
    if st.button("Đặt lại về hiện trạng", icon=":material/restart_alt:", type="tertiary"):
        st.session_state["sc_version"] = version + 1
        st.rerun()
    traffic = dict(zip(edited["Kênh"], edited[TRAFFIC_COL].fillna(0) / 100))
    cr = dict(zip(edited["Kênh"], edited[CR_COL].fillna(0) / 100))
    return traffic, cr


def _waterfall(result: pd.DataFrame, totals: dict) -> go.Figure:
    moved = result[result["delta_revenue"].abs() > 0.005]
    labels = ["Hiện trạng", *moved[BY], "Kịch bản"]
    values = [totals["revenue"], *moved["delta_revenue"], totals["revenue_new"]]
    measures = ["absolute", *["relative"] * len(moved), "total"]
    text = [fmt_value(totals["revenue"], "USD"),
            *[fmt_signed_usd(v) for v in moved["delta_revenue"]],
            fmt_value(totals["revenue_new"], "USD")]
    fig = go.Figure(go.Waterfall(
        x=labels, y=values, measure=measures, text=text, textposition="outside",
        cliponaxis=False, connector=dict(line=dict(color=NEUTRAL, width=1)),
        increasing=dict(marker=dict(color=SERIES[0])), decreasing=dict(marker=dict(color=SERIES[1])),
        totals=dict(marker=dict(color=NEUTRAL)), hovertemplate="%{x}: %{text}<extra></extra>"))
    running = totals["revenue"] + moved["delta_revenue"].cumsum()  # bar tops along the way
    top = max([totals["revenue"], totals["revenue_new"], *running]) or 1
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(range=[0, top * 1.15])  # room for the labels above the bars
    return style_figure(fig, height=380)


def render(ctx: PageContext) -> None:
    """Draw the scenario page."""
    st.title("Mô phỏng kịch bản")
    df = ctx.filtered
    if df.empty:
        st.warning("Không có phiên nào khớp bộ lọc hiện tại.")
        return
    st.caption(
        f"Hiện trạng = hiệu suất từng kênh trong khoảng {ctx.filters.start:%d/%m/%Y} – "
        f"{ctx.filters.end:%d/%m/%Y} theo bộ lọc. Giả định: số đơn trên mỗi phiên mua và giá trị đơn "
        "trung bình (AOV) không đổi; tỷ lệ chuyển đổi tối đa 100%. Dữ liệu không có chi phí quảng "
        "cáo nên mô hình không ước tính được chi phí để đạt lưu lượng mới.")
    note = kpi.data_gap_note(ctx.filters.start, ctx.filters.end)
    if note:
        st.caption(note)

    base = sc.baseline(df, BY)
    st.markdown("**Giả định theo kênh** — nhập % thay đổi vào hai cột cuối")
    traffic, cr = _editor(base)
    result = sc.simulate(base, BY, traffic, cr)
    totals = sc.totals(result)

    m1, m2, m3 = st.columns(3)
    for col, label, unit, old, new in (
        (m1, "Số phiên dự kiến", "phiên", totals["sessions"], totals["sessions_new"]),
        (m2, "Số đơn dự kiến", "đơn", totals["orders"], totals["orders_new"]),
        (m3, "Doanh thu dự kiến", "USD", totals["revenue"], totals["revenue_new"]),
    ):
        value = round(new) if unit != "USD" else new
        col.metric(label, fmt_value(value, unit), delta=fmt_delta(kpi.relative_change(new, old)),
                   border=True, help=f"Hiện trạng: {fmt_value(old, unit)}")

    st.markdown("**Doanh thu: hiện trạng → kịch bản, theo đóng góp của từng kênh**")
    st.plotly_chart(_waterfall(result, totals), width="stretch")

    shown = pd.DataFrame({
        "Kênh": result[BY],
        "Phiên dự kiến": result["sessions_new"].round().map(lambda v: fmt_value(v, "phiên")),
        "CR dự kiến": result["conversion_rate_new"].map(lambda v: fmt_value(v, "%")),
        "Đơn hiện trạng": result["orders"].map(lambda v: fmt_value(v, "đơn")),
        "Đơn dự kiến": result["orders_new"].round().map(lambda v: fmt_value(v, "đơn")),
        "Doanh thu hiện trạng": result["revenue_usd"].map(lambda v: fmt_value(v, "USD")),
        "Doanh thu dự kiến": result["revenue_new"].map(lambda v: fmt_value(v, "USD")),
        "Chênh lệch": result["delta_revenue"].map(fmt_signed_usd),
    })
    st.dataframe(shown, hide_index=True, width="stretch")
