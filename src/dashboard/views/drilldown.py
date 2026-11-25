"""Feature 6 — Drill-down: channel → source/medium → campaign, month → week → day,
product group → product. Click a row to go down, a breadcrumb to go back up."""

import plotly.express as px
import streamlit as st

from src.dashboard import kpi
from src.dashboard.analysis import drilldown as dd
from src.dashboard.context import PageContext
from src.dashboard.formatting import PRIMARY, fmt_value, kpi_display_table, style_figure

SESSION_KPIS = ("sessions", "users", "conversion_rate", "orders", "revenue_usd",
                "revenue_per_session_usd", "revenue_share_total")
SESSION_CHART_KPIS = ("revenue_usd", "sessions", "conversion_rate", "revenue_per_session_usd")
PRODUCT_LABELS = {
    "item_revenue_usd": ("Doanh thu", "USD"),
    "units_sold": ("Số lượng bán", "sản phẩm"),
    "item_checkout_events": ("Lượt checkout", "lượt"),
    "item_add_to_cart_events": ("Lượt thêm giỏ", "lượt"),
    "item_view_events": ("Lượt xem", "lượt"),
    "revenue_share": ("Tỷ trọng doanh thu trong cấp trên", "%"),
}
TOP_BARS = 15


def _paths() -> dict:
    return st.session_state.setdefault("dd_paths", {})


def _set_path(name: str, path: tuple) -> None:
    _paths()[name] = path


def _breadcrumb(hier: dd.Hierarchy, path: tuple) -> None:
    crumbs = [f"Tất cả ({hier.levels[0].label.lower()})"]
    crumbs += [dd.format_key(v, lvl) for v, lvl in zip(path, hier.levels)]
    row = st.container(horizontal=True, vertical_alignment="center", gap="small")
    for i, text in enumerate(crumbs):
        if i:
            row.markdown(":gray[›]", width="content")
        if i == len(path):  # current node: plain bold text, not a button
            row.markdown(f"**{text}**", width="content")
        else:
            row.button(text, key=f"dd_crumb_{i}", type="tertiary",
                       on_click=_set_path, args=(hier.name, path[:i]))


def _metric_options(hier: dd.Hierarchy) -> tuple[list[str], callable, callable]:
    """(metric ids, label function, unit function) for the chart."""
    if hier.source == "products":
        ids = [k for k in PRODUCT_LABELS if k != "revenue_share"]
        return ids, lambda k: PRODUCT_LABELS[k][0], lambda k: PRODUCT_LABELS[k][1]
    return list(SESSION_CHART_KPIS), kpi.label, kpi.unit


def _chart(table, hier: dd.Hierarchy, level: dd.Level) -> None:
    ids, label, unit = _metric_options(hier)
    metric = st.selectbox("Chỉ số trên biểu đồ", ids, format_func=label, key=f"dd_metric_{hier.source}")
    data = table.assign(text=table[metric].map(lambda v: fmt_value(v, unit(metric))))
    if hier.chronological:
        fig = px.bar(data, x="label", y=metric, text="text")
        fig.update_xaxes(type="category")
        height = 360
    else:
        data = data.nlargest(TOP_BARS, metric).iloc[::-1]
        fig = px.bar(data, x=metric, y="label", orientation="h", text="text")
        fig.update_xaxes(range=[0, max(data[metric].max(), 0) * 1.18 or 1])
        height = 60 + 30 * len(data)
    fig.update_traces(marker_color=PRIMARY, textposition="outside", cliponaxis=False,
                      hovertemplate="%{text}<extra></extra>")
    fig.update_layout(hovermode="closest")
    if unit(metric) == "%":
        (fig.update_yaxes if hier.chronological else fig.update_xaxes)(tickformat=".1%")
    st.plotly_chart(style_figure(fig, height=height), width="stretch")
    if not hier.chronological and len(table) > TOP_BARS:
        st.caption(f"Biểu đồ hiển thị {TOP_BARS}/{len(table)} {level.label.lower()} "
                   f"có {label(metric).lower()} cao nhất; bảng bên dưới có đủ.")


def _display_table(table, hier: dd.Hierarchy, level: dd.Level):
    if hier.source == "sessions":
        shown = kpi_display_table(table, "label", level.label, SESSION_KPIS)
        # The share is relative to the parent node, not to channels
        return shown.rename(columns={kpi.label("revenue_share_total"): "Tỷ trọng doanh thu trong cấp trên"})
    shown = table[["label", *PRODUCT_LABELS]].copy()
    for col, (_, unit) in PRODUCT_LABELS.items():
        shown[col] = shown[col].map(lambda v, u=unit: fmt_value(v, u))
    return shown.rename(columns={"label": level.label,
                                 **{k: v[0] for k, v in PRODUCT_LABELS.items()}})


def render(ctx: PageContext) -> None:
    """Draw the drill-down page."""
    st.title("Phân tích chi tiết")
    names = [h.name for h in dd.HIERARCHIES]
    name = st.segmented_control("Hướng phân tích", names, default=names[0], key="dd_hier") or names[0]
    hier = next(h for h in dd.HIERARCHIES if h.name == name)

    base = ctx.filtered_products if hier.source == "products" else ctx.filtered
    df = dd.prepare(base, hier)
    path = _paths().get(name, ())
    if path and dd.subset(df, hier, path).empty:
        # The sidebar filters no longer contain the drilled node: restart at the top
        path = ()
        _set_path(name, path)

    _breadcrumb(hier, path)
    level = hier.levels[len(path)]
    table = dd.level_table(df, hier, path)
    if table.empty:
        st.info("Không có dữ liệu cho bộ lọc hiện tại.")
        return
    table["label"] = table["key"].map(lambda v: dd.format_key(v, level))

    if hier.source == "sessions":
        node = dd.subset(df, hier, path)  # dates of the node being viewed, not of the filter
        note = kpi.data_gap_note(node["session_date"].min(), node["session_date"].max())
        if note:
            st.caption(note)
    if hier.source == "products":
        st.caption("Bộ lọc quốc gia và loại người dùng không áp dụng cho số liệu sản phẩm.")

    _chart(table, hier, level)

    drillable = dd.can_drill(hier, path)
    if drillable:
        next_label = hier.levels[len(path) + 1].label.lower()
        st.caption(f"Chọn một dòng để xem theo {next_label}.")
    event = st.dataframe(
        _display_table(table, hier, level), hide_index=True, width="stretch",
        on_select="rerun" if drillable else "ignore", selection_mode="single-row",
        key=f"dd_table_{hier.source}_{name}_{len(path)}_{hash(path)}",
    )
    if drillable and event and event.selection.rows:
        _set_path(name, path + (table.loc[event.selection.rows[0], "key"],))
        st.rerun()
