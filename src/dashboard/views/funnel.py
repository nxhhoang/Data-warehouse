"""Feature 5 — Conversion funnel: 6 steps, the weakest step, split by segment,
and item-level counts per product group."""

import plotly.express as px
import streamlit as st

from src.dashboard import kpi
from src.dashboard.analysis import funnel
from src.dashboard.config import DIMENSIONS
from src.dashboard.context import PageContext
from src.dashboard.formatting import PRIMARY, fmt_value, style_figure

MIN_SESSIONS = 100
TRANSITIONS = [s.label for s in funnel.STEPS if s.rate_kpi]
# Diverging scale for "segment rate vs overall rate": orange = worse, blue = better
DIVERGING = [[0.0, "#d95926"], [0.5, "#d9d8d4"], [1.0, "#2a78d6"]]


def _pct(v) -> str:
    return fmt_value(v, "%")


def _render_overall(df) -> None:
    table = funnel.funnel_table(df)
    weakest = funnel.weakest_step(table)

    left, right = st.columns(2)
    left.metric(kpi.label("conversion_rate"), _pct(kpi.summarize(df)["conversion_rate"]),
                border=True, help=kpi.kpi_dictionary()["conversion_rate"]["formula_text"])
    if weakest is not None:
        prev = table.loc[weakest.name - 1, "label"]  # RangeIndex: previous step
        right.metric(f"Rời bỏ nhiều nhất: {prev} → {weakest['label']}",
                     _pct(weakest["drop_rate"]), border=True,
                     help="Tỷ lệ phiên có bước trước nhưng không có bước này.")

    fig = px.bar(table, x="sessions", y="label", orientation="h",
                 text=table["sessions"].map(lambda v: fmt_value(v, "phiên")))
    fig.update_traces(marker_color=PRIMARY, textposition="outside", cliponaxis=False,
                      hovertemplate="%{y}: %{x:,.0f} phiên<extra></extra>")
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(hovermode="closest")
    st.plotly_chart(style_figure(fig, height=300), width="stretch")

    shown = table.assign(
        step_rate=table["step_rate"].map(_pct),
        drop_rate=table["drop_rate"].map(_pct),
        share_of_first=table["share_of_first"].map(_pct),
        sessions=table["sessions"].map(lambda v: fmt_value(v, "phiên")),
    ).rename(columns={
        "label": "Bước", "event": "Sự kiện GA4", "sessions": "Số phiên",
        "step_rate": "Tỷ lệ từ bước trước", "drop_rate": "Tỷ lệ rời bỏ",
        "share_of_first": "So với bước đầu",
    })
    st.dataframe(shown, hide_index=True, width="stretch")


def _render_segments(df) -> None:
    names = [n for n in DIMENSIONS if n != "Chiến dịch"]
    dim_label = st.selectbox("Chia theo", names, key="fn_dim")
    by = DIMENSIONS[dim_label]
    rates = funnel.step_rates_by(df, by, MIN_SESSIONS).head(12)
    if rates.empty:
        st.info(f"Không phân khúc nào có từ {MIN_SESSIONS} phiên xem sản phẩm.")
        return

    overall = kpi.summarize(df)
    base = {s.label: overall[s.rate_kpi] for s in funnel.STEPS if s.rate_kpi}
    relative = rates[TRANSITIONS].apply(lambda col: col / base[col.name] - 1)
    text = rates[TRANSITIONS].map(_pct)

    fig = px.imshow(relative.clip(-0.5, 0.5), color_continuous_scale=DIVERGING,
                    zmin=-0.5, zmax=0.5, aspect="auto")
    fig.update_traces(text=text.to_numpy(), texttemplate="%{text}",
                      customdata=relative.to_numpy(),
                      hovertemplate="%{y} · %{x}<br>Tỷ lệ: %{text}"
                                    "<br>So với trung bình: %{customdata:+.0%}<extra></extra>")
    fig.update_layout(coloraxis_colorbar=dict(title="So với<br>trung bình",
                                              tickformat="+.0%"), hovermode="closest")
    fig.update_xaxes(side="top")
    st.plotly_chart(style_figure(fig, height=80 + 42 * len(rates)), width="stretch")
    st.caption(f"Ô cam: tỷ lệ chuyển tiếp thấp hơn trung bình; ô xanh: cao hơn. "
               f"Chỉ hiển thị phân khúc có từ {MIN_SESSIONS} phiên xem sản phẩm (tối đa 12).")

    weakest = relative.idxmin(axis=1)
    gaps = [relative.loc[i, w] for i, w in weakest.items()]
    # Within 1% of the average on every step: no weak step to point at
    summary = rates[["view_sessions", "conversion_rate"]].assign(
        weakest=[w if g < -0.01 else "Không có (mọi bước ≥ trung bình)" for w, g in zip(weakest, gaps)],
        gap=[g if g < -0.01 else None for g in gaps],
    ).reset_index()
    summary["view_sessions"] = summary["view_sessions"].map(lambda v: fmt_value(v, "phiên"))
    summary["conversion_rate"] = summary["conversion_rate"].map(_pct)
    summary["gap"] = summary["gap"].map(lambda v: "" if v is None or v != v else f"{v:+.0%}")
    st.dataframe(summary.rename(columns={
        by: dim_label, "view_sessions": "Phiên xem SP", "conversion_rate": "Tỷ lệ chuyển đổi",
        "weakest": "Bước yếu nhất so với trung bình", "gap": "Chênh lệch",
    }), hide_index=True, width="stretch")


def _render_products(ctx: PageContext) -> None:
    st.warning(
        "Trong bộ dữ liệu đã làm mờ, sản phẩm ở bước xem/thêm giỏ và sản phẩm được mua gần như "
        "là hai danh mục khác nhau (4/427 mã sản phẩm được xem từng được bán), nên không tính "
        "tỷ lệ xem → mua theo sản phẩm. Chỉ bước checkout và mua dùng chung mã sản phẩm.",
        icon=":material/info:")
    products = ctx.filtered_products
    if products.empty:
        st.info("Không có dữ liệu sản phẩm cho bộ lọc hiện tại.")
        return
    table = funnel.product_stage_table(products).head(20).reset_index()
    for col in ("item_view_events", "item_add_to_cart_events", "item_checkout_events", "units_sold"):
        table[col] = table[col].map(lambda v: fmt_value(v, "lượt"))
    table["item_revenue_usd"] = table["item_revenue_usd"].map(lambda v: fmt_value(v, "USD"))
    table["units_per_checkout"] = table["units_per_checkout"].map(lambda v: fmt_value(v, "x"))
    st.dataframe(table.rename(columns={
        "item_category": "Nhóm sản phẩm", "item_view_events": "Lượt xem",
        "item_add_to_cart_events": "Lượt thêm giỏ", "item_checkout_events": "Lượt checkout",
        "units_sold": "Số lượng bán", "item_revenue_usd": "Doanh thu",
        "units_per_checkout": "SL bán / lượt checkout",
    }), hide_index=True, width="stretch")
    st.caption("20 nhóm có doanh thu cao nhất. Bộ lọc quốc gia và loại người dùng không áp dụng "
               "cho số liệu sản phẩm.")


def render(ctx: PageContext) -> None:
    """Draw the funnel page."""
    st.title("Phễu chuyển đổi")
    tracked_only = st.toggle(
        "Chỉ tính các ngày có ghi nhận add_to_cart", value=True, key="fn_tracked",
        help="add_to_cart vắng mặt trong 18/92 ngày. Bỏ các ngày đó để tỷ lệ thêm giỏ và "
             "bắt đầu thanh toán không bị méo; tắt để khớp định nghĩa trong kpi_dictionary.")
    df = funnel.tracked_days_only(ctx.filtered) if tracked_only else ctx.filtered
    if df.empty or df["has_view_item"].sum() == 0:
        st.warning("Không có phiên xem sản phẩm nào khớp bộ lọc hiện tại.")
        return
    st.caption("Mỗi bước đếm số phiên có sự kiện đó, không yêu cầu đúng thứ tự: dữ liệu chỉ có "
               "cờ theo phiên, và một số phiên mua hàng không ghi nhận add_to_cart.")

    overall, segments, products = st.tabs(["Phễu tổng", "Theo phân khúc", "Theo nhóm sản phẩm"])
    with overall:
        _render_overall(df)
    with segments:
        _render_segments(df)
    with products:
        _render_products(ctx)
