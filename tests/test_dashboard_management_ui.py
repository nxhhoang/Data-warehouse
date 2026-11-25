"""UI regression tests for the pinned management-tab navigation."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).parents[1] / "src" / "dashboard" / "app.py"
EXPECTATIONS = {
    "all": (
        "Tổng quan điều hành",
        ["Tổng quan", "So sánh hiệu suất", "Chất lượng kênh",
         "Phễu chuyển đổi", "Phân tích chi tiết", "Phân khúc khách hàng",
         "Cảnh báo theo ngưỡng", "Mô phỏng kịch bản", "Truy vết số liệu"],
    ),
    "cmo": (
        "Tổng quan điều hành",
        ["Tổng quan", "So sánh hiệu suất", "Chất lượng kênh",
         "Cảnh báo theo ngưỡng", "Mô phỏng kịch bản", "Truy vết số liệu"],
    ),
    "manager": (
        "So sánh hiệu suất",
        ["So sánh hiệu suất", "Chất lượng kênh", "Phân tích chi tiết",
         "Cảnh báo theo ngưỡng", "Mô phỏng kịch bản", "Truy vết số liệu"],
    ),
    "specialist": (
        "Phễu chuyển đổi",
        ["Phễu chuyển đổi", "Phân tích chi tiết",
         "Phân khúc khách hàng", "Truy vết số liệu"],
    ),
}


def test_management_tabs_have_expected_options_and_page_links():
    initial = AppTest.from_file(str(APP), default_timeout=60)
    initial.run()
    assert len(initial.exception) == 0
    assert initial.sidebar.segmented_control[0].value == "all"

    for role, (title, labels) in EXPECTATIONS.items():
        app = AppTest.from_file(str(APP), default_timeout=60)
        app.session_state["management_role"] = role
        app.run()
        assert len(app.exception) == 0, f"render failed for role={role}"
        assert [item.value for item in app.title] == [title]
        assert [item.label for item in app.sidebar.page_link] == labels


def test_filter_panel_starts_collapsed_and_keeps_functionality():
    app = AppTest.from_file(str(APP), default_timeout=60)
    app.run()
    assert len(app.exception) == 0
    filter_panels = [panel for panel in app.sidebar.expander if panel.label == "Bộ lọc"]
    assert len(filter_panels) == 1
    # Widgets must live inside the expander, not as siblings on st.sidebar.
    widget_types = {child.__class__.__name__ for child in filter_panels[0].children.values()}
    assert {"Caption", "DateInput", "Radio", "Multiselect"} <= widget_types
