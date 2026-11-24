"""Feature 8 — Threshold alerts: channels/campaigns whose KPIs moved past
user-set thresholds between the latest window and the one before it."""

import streamlit as st

from src.dashboard import kpi
from src.dashboard.analysis import alerts as al
from src.dashboard.analysis.funnel import tracked_days_only
from src.dashboard.context import PageContext
from src.dashboard.filters import apply_filters
from src.dashboard.formatting import fmt_value

GROUPINGS = {"Kênh": "channel_group", "Chiến dịch": "campaign", "Nguồn / Medium": "source_medium"}
WINDOWS = {"7 ngày": 7, "14 ngày": 14, "28 ngày": 28}
# Reserved status colours, always paired with the text label
STATUS_STYLE = {
    al.SERIOUS: "background-color: #fde2e1; color: #9f1f1b; font-weight: 600",
    al.WARNING: "background-color: #fef0c7; color: #7a4b00; font-weight: 600",
}


def _pct_slider(label: str, default: float, key: str, help: str) -> float:
    return st.slider(label, 5, 100, int(round(default * 100)), step=5, format="%d%%",
                     key=key, help=help) / 100


def render(ctx: PageContext) -> None:
    """Draw the alerts page."""
    st.title("Cảnh báo theo ngưỡng")
    sessions, f = ctx.sessions, ctx.filters

    left, mid, right = st.columns(3)
    group_label = left.segmented_control("Theo dõi theo", list(GROUPINGS), default="Kênh",
                                         key="al_group") or "Kênh"
    window_label = mid.segmented_control("Cửa sổ so sánh", list(WINDOWS), default="7 ngày",
                                         key="al_window") or "7 ngày"
    min_sessions = right.number_input("Số phiên tối thiểu mỗi kỳ", 10, 10_000, 100, step=50,
                                      key="al_min")
    with st.expander("Ngưỡng cảnh báo", expanded=True, icon=":material/tune:"):
        c1, c2, c3 = st.columns(3)
        with c1:
            drop = _pct_slider("Giảm từ", ctx.settings.alert_threshold, "al_drop",
                               "Tỷ lệ chuyển đổi, doanh thu hoặc số phiên giảm ít nhất mức này.")
        with c2:
            rise = _pct_slider("Tỷ lệ rời bỏ giỏ tăng từ", ctx.settings.alert_threshold, "al_rise",
                               "Tính trên các ngày có ghi nhận add_to_cart.")
        with c3:
            spike = _pct_slider("Lưu lượng tăng đột biến từ", 0.5, "al_spike",
                                "Số phiên tăng ít nhất mức này mà tỷ lệ chuyển đổi không tăng.")
        st.caption("Mức Nghiêm trọng khi thay đổi vượt gấp đôi ngưỡng.")

    by = GROUPINGS[group_label]
    previous_w, current_w = al.windows(f.end, WINDOWS[window_label])
    if previous_w[0] < sessions["session_date"].min():
        st.warning("Không đủ dữ liệu cho kỳ trước: chọn ngày kết thúc muộn hơn ở thanh bên "
                   "hoặc cửa sổ ngắn hơn.")
        return
    st.caption(f"Kỳ hiện tại {current_w[0]:%d/%m/%Y} – {current_w[1]:%d/%m/%Y} so với "
               f"{previous_w[0]:%d/%m/%Y} – {previous_w[1]:%d/%m/%Y} (kết thúc theo ngày cuối của "
               "bộ lọc). Bộ lọc kênh, thiết bị, quốc gia, loại người dùng vẫn áp dụng.")
    for note in {kpi.data_gap_note(*previous_w), kpi.data_gap_note(*current_w)} - {None}:
        st.warning(note + " Cảnh báo về doanh thu và chuyển đổi trong kỳ này không đáng tin.",
                   icon=":material/info:")

    previous = apply_filters(sessions, f.with_dates(*previous_w))
    current = apply_filters(sessions, f.with_dates(*current_w))
    table = al.evaluate(previous, current, by, al.Thresholds(drop, rise, spike), min_sessions,
                        tracked_days_only(previous), tracked_days_only(current))

    groups = set(previous[by]) & set(current[by])
    m1, m2, m3 = st.columns(3)
    m1.metric("Cảnh báo nghiêm trọng", int((table["severity"] == al.SERIOUS).sum()), border=True)
    m2.metric("Cảnh báo", int((table["severity"] == al.WARNING).sum()), border=True)
    m3.metric(f"{group_label} được theo dõi", len(groups), border=True)

    if table.empty:
        st.success("Không có chỉ số nào vượt ngưỡng trong kỳ này.", icon=":material/check_circle:")
        return
    shown = table.assign(
        previous=[fmt_value(v, kpi.unit(k)) for v, k in zip(table["previous"], table["kpi_id"])],
        current=[fmt_value(v, kpi.unit(k)) for v, k in zip(table["current"], table["kpi_id"])],
        change=table["change"].map(lambda v: ("+" if v >= 0 else "") + fmt_value(v, "%")),
    )[["severity", "group", "rule", "previous", "current", "change"]].rename(columns={
        "severity": "Mức độ", "group": group_label, "rule": "Quy tắc",
        "previous": "Kỳ trước", "current": "Kỳ hiện tại", "change": "Thay đổi",
    })
    st.dataframe(shown.style.map(lambda v: STATUS_STYLE.get(v, ""), subset=["Mức độ"]),
                 hide_index=True, width="stretch")
