"""Marketing DSS dashboard — entry point (layer 5).

Run from the repository root:
    streamlit run src/dashboard/app.py

DASHBOARD_DATA_SOURCE in .env selects the data: 'mock' (default, no GCP)
or 'bigquery' (needs GCP_PROJECT_ID and `gcloud auth application-default login`).
"""

import sys
from pathlib import Path

# `streamlit run` puts only src/dashboard on sys.path; modules import `src.*`
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from src.dashboard.config import Settings, get_settings  # noqa: E402
from src.dashboard.context import PageContext  # noqa: E402
from src.dashboard.data import load_products, load_sessions  # noqa: E402
from src.dashboard.filters import render_sidebar  # noqa: E402
from src.dashboard.roles import ROLE_LABELS, ROLE_OPTIONS, allowed_paths  # noqa: E402
from src.dashboard.views import (alerts, channel_quality, compare, drilldown,  # noqa: E402
                                 funnel, overview, scenario, segments, trace)

CACHE_TTL_SEC = 3600


@st.cache_data(ttl=CACHE_TTL_SEC, show_spinner="Đang tải dữ liệu phiên…")
def cached_sessions(source: str, project_id: str):
    return load_sessions(Settings(source, project_id, 0.0))


@st.cache_data(ttl=CACHE_TTL_SEC, show_spinner="Đang tải dữ liệu sản phẩm…")
def cached_products(source: str, project_id: str):
    return load_products(Settings(source, project_id, 0.0))


def main() -> None:
    st.set_page_config(page_title="Marketing DSS", page_icon=":material/insights:",
                       layout="wide")
    settings = get_settings()
    role = st.sidebar.segmented_control(
        "Chế độ quản lý", options=ROLE_OPTIONS,
        format_func=ROLE_LABELS.get, default="all",
        selection_mode="single", key="management_role",
    )
    try:
        sessions = cached_sessions(settings.data_source, settings.project_id)
        products = cached_products(settings.data_source, settings.project_id)
    except Exception as exc:  # surface config/auth problems instead of a stack trace
        st.error(f"Không tải được dữ liệu ({settings.data_source}): {exc}")
        st.stop()

    if settings.data_source == "mock":
        st.sidebar.warning("Đang dùng dữ liệu giả lập (mock).", icon=":material/science:")
    ctx = PageContext(settings, sessions, products, render_sidebar(sessions))

    def page(fn, title, url_path, **kwargs):
        # Explicit url_path: lambdas have no meaningful __name__
        return st.Page(fn, title=title, url_path=url_path, **kwargs)

    registry = [
        ("tong-quan", "1. Tổng quan", overview.render),
        ("so-sanh", "3. So sánh hiệu suất", compare.render),
        ("chat-luong-kenh", "4. Chất lượng kênh", channel_quality.render),
        ("pheu", "5. Phễu chuyển đổi", funnel.render),
        ("chi-tiet", "6. Phân tích chi tiết", drilldown.render),
        ("phan-khuc", "7. Phân khúc khách hàng", segments.render),
        ("canh-bao", "8. Cảnh báo theo ngưỡng", alerts.render),
        ("mo-phong", "9. Mô phỏng kịch bản", scenario.render),
        ("truy-vet", "10. Truy vết số liệu", trace.render),
    ]
    visible_paths = allowed_paths(role)
    ctx.pages = {
        path: page(lambda render=render: render(ctx), title, path,
                   default=(path == visible_paths[0]))
        for path, title, render in registry if path in visible_paths
    }

    # Switch to the selected role's home only when the role itself changes.
    # Plain page-link navigation and direct URLs are handled by st.Page below.
    if st.session_state.get("_last_management_role") not in (None, role):
        st.session_state["_last_management_role"] = role
        st.switch_page(ctx.pages[visible_paths[0]])
    st.session_state["_last_management_role"] = role

    st.sidebar.divider()
    for path, title, _ in registry:
        if path in visible_paths:
            st.sidebar.page_link(ctx.pages[path], label=title)
    st.navigation([ctx.pages[path] for path in visible_paths],
                  position="hidden").run()


main()
