"""Feature 4 — Channel quality: traffic volume (x) versus traffic quality (y),
bubble size = revenue, four quadrants with a suggested action."""

import numpy as np
import plotly.express as px
import streamlit as st

from src.dashboard import kpi
from src.dashboard.analysis import channel_quality as cq
from src.dashboard.context import PageContext
from src.dashboard.formatting import NEUTRAL, PRIMARY, fmt_value, kpi_display_table, style_figure

MIN_SESSIONS = 100
TOP_SOURCES = 15
DIMENSIONS = {"Kênh": "channel_group", "Nguồn / Medium": "source_medium"}
BASE_TABLE_KPIS = ("sessions", "revenue_usd", "revenue_share_total")


def _scatter(table, by: str, quality_kpi: str, volume_cut: float, quality_cut: float):
    eligible = table[table["quadrant"] != cq.SMALL]
    fig = px.scatter(eligible, x="sessions", y=quality_kpi, size="revenue_usd", size_max=48,
                     text=by, log_x=True, custom_data=["quadrant", "revenue_usd"])
    fig.update_traces(
        marker=dict(color=PRIMARY, opacity=0.75, line=dict(width=2, color="white")),
        textposition="top center",
        hovertemplate="<b>%{text}</b><br>Số phiên: %{x:,.0f}<br>%{y}"
                      "<br>Doanh thu: $%{customdata[1]:,.0f}<br>%{customdata[0]}<extra></extra>")
    fig.add_vline(x=volume_cut, line=dict(color=NEUTRAL, width=1, dash="dot"))
    fig.add_hline(y=quality_cut, line=dict(color=NEUTRAL, width=1, dash="dot"))
    # Quadrant names in the corners, in muted text
    for x, y, name, xa, ya in ((0.99, 0.99, cq.CORE, "right", "top"),
                               (0.99, 0.01, cq.LEAKY, "right", "bottom"),
                               (0.01, 0.99, cq.NICHE, "left", "top"),
                               (0.01, 0.01, cq.WEAK, "left", "bottom")):
        fig.add_annotation(x=x, y=y, xref="paper", yref="paper", text=name, showarrow=False,
                           xanchor=xa, yanchor=ya, font=dict(color=NEUTRAL, size=12))
    fig.update_layout(hovermode="closest")
    # Readable log ticks (plotly's default shows 2, 5 minor labels) and headroom so
    # point labels clear the corner annotations
    lo, hi = eligible["sessions"].min(), eligible["sessions"].max()
    ticks = [10 ** k for k in range(int(np.floor(np.log10(lo))), int(np.ceil(np.log10(hi))) + 1)]
    fig.update_xaxes(title="Số phiên (thang log)", tickvals=ticks,
                     ticktext=[fmt_value(t, "phiên") for t in ticks])
    ymax = eligible[quality_kpi].max()
    fig.update_yaxes(range=[-0.08 * ymax, 1.25 * ymax])
    if kpi.unit(quality_kpi) == "%":
        fig.update_yaxes(tickformat=".1%")
    return style_figure(fig, height=460)


def render(ctx: PageContext) -> None:
    """Draw the channel quality page."""
    st.title("Chất lượng kênh")
    df = ctx.filtered
    if df.empty:
        st.warning("Không có phiên nào khớp bộ lọc hiện tại.")
        return

    left, right = st.columns(2)
    dim_label = left.segmented_control("Phân tích theo", list(DIMENSIONS), default="Kênh",
                                       key="cq_dim") or "Kênh"
    quality_kpi = right.selectbox("Chỉ số chất lượng", cq.QUALITY_KPIS, format_func=kpi.label,
                                  key="cq_metric")
    by = DIMENSIONS[dim_label]
    if by == "source_medium":
        top = df["source_medium"].value_counts().index[:TOP_SOURCES]
        df = df[df["source_medium"].isin(top)]

    table, volume_cut, quality_cut = cq.classify(df, by, quality_kpi, MIN_SESSIONS)
    if np.isnan(volume_cut):
        st.info(f"Không nhóm nào có từ {MIN_SESSIONS} phiên để phân loại.")
        return

    st.plotly_chart(_scatter(table, by, quality_kpi, volume_cut, quality_cut), width="stretch")
    st.caption(
        f"Đường dọc: trung vị số phiên ({fmt_value(volume_cut, 'phiên')}). "
        f"Đường ngang: {kpi.label(quality_kpi).lower()} trung bình của phạm vi đang lọc "
        f"({fmt_value(quality_cut, kpi.unit(quality_kpi))}). Kích thước bong bóng: doanh thu."
        + (f" Chỉ gồm {TOP_SOURCES} nguồn / medium nhiều phiên nhất." if by == "source_medium" else ""))

    order = [cq.CORE, cq.LEAKY, cq.NICHE, cq.WEAK, cq.SMALL]
    table["_order"] = table["quadrant"].map(order.index)
    table = table.sort_values(["_order", "sessions"], ascending=[True, False])
    table_kpis = (BASE_TABLE_KPIS[0], quality_kpi, *BASE_TABLE_KPIS[1:])
    shown = kpi_display_table(table, by, dim_label, table_kpis,
                              extra={"quadrant": "Phân loại", "advice": "Gợi ý"})
    st.dataframe(shown, hide_index=True, width="stretch")
    if (table["quadrant"] == cq.SMALL).any():
        st.caption(f"Nhóm dưới {MIN_SESSIONS} phiên không được đưa lên biểu đồ.")
