"""Feature 10 — Number traceability: from a KPI value to its definition, its
numerator and denominator, the lineage path, the source sessions, data
quality notes, and an independent recomputation on the warehouse."""

import streamlit as st

from src.dashboard import kpi
from src.dashboard.analysis import trace
from src.dashboard.context import PageContext
from src.dashboard.data import run_query
from src.dashboard.filters import USER_TYPES
from src.dashboard.formatting import fmt_value

# Set by other pages (e.g. the overview's "Truy vết" buttons) before switching here
REQUEST_KEY = "trace_kpi"
SHOWN_RECORDS = 200


def _filter_summary(ctx: PageContext) -> str:
    f = ctx.filters
    parts = [f"{f.start:%d/%m/%Y} – {f.end:%d/%m/%Y}"]
    for label, values in (("Kênh", f.channels), ("Thiết bị", f.devices), ("Quốc gia", f.countries)):
        if values:
            parts.append(f"{label}: {', '.join(values)}")
    if f.user_type != USER_TYPES[0]:
        parts.append(f.user_type)
    return " · ".join(parts)


def _quality_notes(ctx: PageContext, kpi_id: str) -> list[str]:
    notes = list(kpi.kpi_dictionary()[kpi_id].get("caveats", []))
    order_note = kpi.data_gap_note(ctx.filters.start, ctx.filters.end)
    if order_note and kpi_id in kpi.ORDER_KPIS:
        notes.append(order_note)
    if kpi_id in kpi.CART_DEPENDENT and not any("18/92" in n for n in notes):
        notes.append("add_to_cart vắng mặt trong 18/92 ngày; tỷ lệ phụ thuộc giỏ hàng bị méo "
                     "nếu khoảng thời gian có các ngày đó.")
    if kpi_id in ("orders", "revenue_usd", "aov_usd", "conversion_rate"):
        notes.append("Giao dịch hợp lệ: purchase có transaction_id khác NULL/'(not set)', doanh "
                     "thu > 0, khử trùng theo (user_pseudo_id, transaction_id). Quy tắc này loại "
                     "883 purchase có transaction_id '(not set)' (31.817 USD) trong 92 ngày.")
    return notes


def _verify(ctx: PageContext, kpi_id: str, parts: dict) -> None:
    sql, params = trace.verification_sql(kpi_id, ctx.filters, ctx.settings.project_id or "<project>")
    with st.expander("SQL tính lại từ tầng Core", icon=":material/code:"):
        st.code(sql, language="sql")
        st.caption("Tham số: " + ", ".join(f"@{n} = {v}" for n, _, v in params))
    if ctx.settings.data_source != "bigquery":
        st.info("Đối chiếu trực tiếp với kho chỉ chạy ở chế độ DASHBOARD_DATA_SOURCE=bigquery.")
        return
    if not st.button("Chạy đối chiếu trên BigQuery", icon=":material/fact_check:"):
        return
    with st.spinner("Đang truy vấn tầng Core…"):
        row = run_query(ctx.settings, sql, params).iloc[0]
    checks = [("Tử số" if parts["denominator"] else "Giá trị", parts["numerator"][1], row["numerator"])]
    if parts["denominator"]:
        checks.append(("Mẫu số", parts["denominator"][1], row["denominator"]))
    ok = all(abs(float(dash) - float(dw)) <= 0.01 for _, dash, dw in checks)
    for label, dash, dw in checks:
        st.write(f"{label}: dashboard **{fmt_value(float(dash), 'x')}** · kho **{fmt_value(float(dw), 'x')}**")
    if ok:
        st.success("Khớp: con số trên dashboard bằng kết quả tính trực tiếp từ kho.",
                   icon=":material/check_circle:")
    else:
        st.error("Lệch giữa dashboard và kho, cần kiểm tra lại dữ liệu đã tải hoặc bộ lọc.",
                 icon=":material/error:")


def render(ctx: PageContext) -> None:
    """Draw the traceability page."""
    st.title("Truy vết số liệu")
    ids = trace.traceable_kpis()
    if REQUEST_KEY in st.session_state:
        st.session_state["tv_kpi"] = st.session_state.pop(REQUEST_KEY)
    kpi_id = st.selectbox("Chỉ số", ids, format_func=kpi.label, key="tv_kpi")
    meta = kpi.kpi_dictionary()[kpi_id]
    df = ctx.filtered
    parts = trace.components(df, kpi_id)
    unit = meta["unit"]

    left, right = st.columns([1, 2])
    left.metric(meta["name"], fmt_value(parts["value"], unit), border=True)
    left.caption(f"Bộ lọc: {_filter_summary(ctx)}")
    with right:
        st.markdown(f"**Nhóm:** {meta['group']}  \n**Công thức:** {meta['formula_text']}")
        st.code(meta["sql_formula"], language="sql")

    st.subheader("Tử số và mẫu số")
    cols = st.columns(3 if parts["denominator"] else 2)
    num_label, num = parts["numerator"]
    cols[0].metric(num_label, fmt_value(num, "USD" if "USD" in num_label else "x"), border=True)
    if parts["denominator"]:
        den_label, den = parts["denominator"]
        cols[1].metric(den_label, fmt_value(den, "x"), border=True)
        formula = {"ratio": "Tử số / Mẫu số", "one_minus_ratio": "1 − Tử số / Mẫu số"}[parts["shape"]]
        cols[2].metric(f"Giá trị = {formula}", fmt_value(parts["value"], unit), border=True)
    else:
        cols[1].metric("Giá trị", fmt_value(parts["value"], unit), border=True)

    st.subheader("Đường đi dữ liệu")
    st.graphviz_chart(trace.lineage_dot(kpi_id), width="stretch")

    st.subheader("Bản ghi nguồn")
    records = trace.source_records(df, kpi_id)
    st.caption(f"{fmt_value(len(records), 'phiên')} phiên tạo nên con số này; bảng hiển thị "
               f"{min(SHOWN_RECORDS, len(records))} phiên có doanh thu cao nhất. Cờ 1/0 cho biết "
               "phiên có được tính vào tử số/mẫu số hay không.")
    shown = records.head(SHOWN_RECORDS).assign(
        session_date=lambda d: d["session_date"].dt.strftime("%d/%m/%Y"))
    st.dataframe(shown, hide_index=True, width="stretch")
    csv = records.assign(session_date=records["session_date"].dt.date).to_csv(index=False)
    st.download_button("Tải toàn bộ bản ghi (CSV)", csv.encode("utf-8"),
                       file_name=f"truy_vet_{kpi_id}.csv", mime="text/csv",
                       icon=":material/download:")

    st.subheader("Ghi chú chất lượng dữ liệu")
    for note in _quality_notes(ctx, kpi_id):
        st.markdown(f"- {note}")

    st.subheader("Đối chiếu với kho dữ liệu")
    _verify(ctx, kpi_id, parts)
