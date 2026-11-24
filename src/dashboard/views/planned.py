"""Placeholder for features not built yet: shows the scope and data sources
agreed in the report (section 3.5) so the navigation is complete from day one.
Replace an entry with a real module in views/ when the feature is built."""

from dataclasses import dataclass

import streamlit as st

from src.dashboard.context import PageContext


@dataclass(frozen=True)
class PlannedFeature:
    number: int
    title: str
    url_path: str
    scope: str
    data: str


PLANNED = (
    PlannedFeature(7, "Phân khúc khách hàng", "phan-khuc",
                   "Nhóm theo thiết bị, vùng, nguồn truy cập, người dùng mới/cũ, mức tương tác.",
                   "sessions (is_new_user là cờ cấp người dùng)"),
    PlannedFeature(8, "Cảnh báo theo ngưỡng", "canh-bao",
                   "Đánh dấu kênh/chiến dịch có chỉ số giảm quá ngưỡng so với kỳ trước; "
                   "ngưỡng do người dùng cấu hình (mặc định ALERT_DEFAULT_THRESHOLD).",
                   "sessions, kpi.previous_period"),
    PlannedFeature(9, "Mô phỏng kịch bản", "mo-phong",
                   "Điều chỉnh lưu lượng/tỷ lệ chuyển đổi từng kênh, ước tính số đơn và doanh thu.",
                   "sessions (hiệu suất lịch sử theo kênh)"),
    PlannedFeature(10, "Truy vết số liệu", "truy-vet",
                   "Từ một con số xem công thức, đường đi dữ liệu và bản ghi nguồn.",
                   "kpi_dictionary.yaml + src/kpi/lineage.py (MetricLineageService)"),
)


def render(feature: PlannedFeature, ctx: PageContext) -> None:
    """Draw the placeholder page of ``feature``."""
    st.title(feature.title)
    st.info(f"Chức năng {feature.number} — chưa hiện thực.")
    st.markdown(f"**Phạm vi:** {feature.scope}")
    st.markdown(f"**Nguồn dữ liệu:** {feature.data}")
    st.caption(f"Bộ lọc hiện tại khớp {len(ctx.filtered):,} phiên.".replace(",", "."))
