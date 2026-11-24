"""Feature 7 — Customer segmentation: profile segments of one dimension against
the average, or cross two dimensions in a matrix."""

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.dashboard import kpi
from src.dashboard.analysis import segments as seg
from src.dashboard.config import DIMENSIONS
from src.dashboard.context import PageContext
from src.dashboard.formatting import SERIES, fmt_value, kpi_display_table, style_figure

SEGMENT_DIMENSIONS = ("Thiết bị", "Châu lục", "Quốc gia", "Kênh", "Người dùng mới/cũ",
                      "Mức tương tác", "Loại trang vào")
ORDERS = {"engagement_level": seg.ENGAGEMENT_LEVELS}
TOP_SEGMENTS = 15
MIN_SESSIONS = 100
# Sequential single-hue ramp (light -> dark) for magnitude
BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def _fmt_index(v) -> str:
    return "—" if v != v else f"{v:.2f}×".replace(".", ",")


def _render_profile(df) -> None:
    dim_label = st.selectbox("Phân khúc theo", SEGMENT_DIMENSIONS, index=5, key="sg_dim")
    by = DIMENSIONS[dim_label]
    table = seg.segment_profile(df, by, ORDERS.get(by))
    if by not in ORDERS:
        table = table.head(TOP_SEGMENTS)

    # Where the sessions are versus where the revenue is
    shares = table.melt(id_vars=[by], value_vars=["session_share", "revenue_share_total"],
                        var_name="measure", value_name="share")
    shares["measure"] = shares["measure"].map({"session_share": "Tỷ trọng phiên",
                                               "revenue_share_total": "Tỷ trọng doanh thu"})
    fig = px.bar(shares, x="share", y=by, color="measure", orientation="h", barmode="group",
                 color_discrete_map={"Tỷ trọng phiên": SERIES[0], "Tỷ trọng doanh thu": SERIES[1]},
                 category_orders={by: list(table[by])})
    fig.update_traces(hovertemplate="%{y}: %{x:.1%}<extra>%{fullData.name}</extra>")
    fig = style_figure(fig, height=80 + 46 * len(table))
    fig.update_layout(showlegend=True, hovermode="closest",
                      legend=dict(title=None, orientation="h", y=1.06, x=0))
    fig.update_xaxes(tickformat=".0%")
    st.markdown(f"**Tỷ trọng phiên và doanh thu theo {dim_label.lower()}**")
    st.plotly_chart(fig, width="stretch")

    big = table[table["sessions"] >= MIN_SESSIONS]
    if not big.empty and big["rps_index"].notna().any():
        best = big.loc[big["rps_index"].idxmax()]
        st.info(f"**{best[by]}** chiếm {fmt_value(best['session_share'], '%')} số phiên nhưng "
                f"{fmt_value(best['revenue_share_total'], '%')} doanh thu; doanh thu mỗi phiên "
                f"gấp {_fmt_index(best['rps_index'])} mức trung bình.", icon=":material/insights:")

    shown = kpi_display_table(table, by, dim_label, seg.PROFILE_KPIS)
    shown.insert(2, "Tỷ trọng phiên", table["session_share"].map(lambda v: fmt_value(v, "%")))
    shown["Chỉ số CR (TB = 1)"] = table["cr_index"].map(_fmt_index)
    shown["Chỉ số DT/phiên (TB = 1)"] = table["rps_index"].map(_fmt_index)
    st.dataframe(shown, hide_index=True, width="stretch")
    note = []
    if by not in ORDERS and len(table) == TOP_SEGMENTS:
        note.append(f"Hiển thị {TOP_SEGMENTS} phân khúc nhiều phiên nhất.")
    if by == "user_type":
        note.append("Người dùng mới = phiên chứa first_visit; người dùng đã ghé trước 01/11/2020 "
                    "chỉ xuất hiện ở nhóm cũ.")
    if note:
        st.caption(" ".join(note))


def _render_cross(df) -> None:
    left, mid, right = st.columns(3)
    rows_label = left.selectbox("Hàng", SEGMENT_DIMENSIONS, index=5, key="sg_rows")
    col_options = [d for d in SEGMENT_DIMENSIONS if d != rows_label]
    cols_label = mid.selectbox("Cột", col_options, index=col_options.index("Thiết bị")
                               if "Thiết bị" in col_options else 0, key="sg_cols")
    kpi_id = right.selectbox("Chỉ số", seg.CROSS_KPIS, format_func=kpi.label, key="sg_kpi")
    rows, cols = DIMENSIONS[rows_label], DIMENSIONS[cols_label]

    values, sessions = seg.cross_tab(df, rows, cols, kpi_id, MIN_SESSIONS)
    if rows in ORDERS:
        values = values.reindex([v for v in ORDERS[rows] if v in values.index])
        sessions = sessions.reindex(values.index)
    unit = kpi.unit(kpi_id)
    text = values.map(lambda v: "" if v != v else fmt_value(v, unit))
    fig = go.Figure(go.Heatmap(
        z=values.to_numpy(), x=[str(c) for c in values.columns], y=[str(r) for r in values.index],
        text=text.to_numpy(), texttemplate="%{text}", customdata=sessions.to_numpy(),
        colorscale=BLUES, hoverongaps=False, showscale=False,
        hovertemplate="%{y} · %{x}<br>%{text}<br>%{customdata:,} phiên<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(side="top")
    fig.update_layout(hovermode="closest")
    st.plotly_chart(style_figure(fig, height=90 + 44 * len(values)), width="stretch")
    st.caption(f"Ô đậm hơn: {kpi.label(kpi_id).lower()} cao hơn. Ô trống: dưới {MIN_SESSIONS} phiên. "
               "Mỗi chiều giữ tối đa 8 giá trị nhiều phiên nhất.")


def render(ctx: PageContext) -> None:
    """Draw the segmentation page."""
    st.title("Phân khúc khách hàng")
    df = ctx.filtered
    if df.empty:
        st.warning("Không có phiên nào khớp bộ lọc hiện tại.")
        return
    profile, cross = st.tabs(["Hồ sơ phân khúc", "Ma trận hai chiều"])
    with profile:
        _render_profile(df)
    with cross:
        _render_cross(df)
