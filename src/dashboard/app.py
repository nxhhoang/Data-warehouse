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
from src.dashboard.views import channel_quality, compare, funnel, overview, planned  # noqa: E402

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

    nav = st.navigation({
        "Bản cơ bản (M5)": [
            page(lambda: overview.render(ctx), "1. Tổng quan", "tong-quan", default=True),
            page(lambda: compare.render(ctx), "3. So sánh hiệu suất", "so-sanh"),
            page(lambda: channel_quality.render(ctx), "4. Chất lượng kênh", "chat-luong-kenh"),
            page(lambda: funnel.render(ctx), "5. Phễu chuyển đổi", "pheu"),
            *[page(lambda f=f: planned.render(f, ctx), f"{f.number}. {f.title}", f.url_path)
              for f in planned.PLANNED if f.milestone == "M5"],
        ],
        "Nâng cao (M6)": [
            page(lambda f=f: planned.render(f, ctx), f"{f.number}. {f.title}", f.url_path)
            for f in planned.PLANNED if f.milestone == "M6"
        ],
    })
    nav.run()


main()
