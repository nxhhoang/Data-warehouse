"""UI regression tests for the pinned management-tab navigation."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture(autouse=True)
def use_mock_dashboard(monkeypatch):
    """Keep UI tests local even when the developer's .env uses BigQuery."""
    monkeypatch.setenv("DASHBOARD_DATA_SOURCE", "mock")

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
    labels = {child.label for child in filter_panels[0].children.values()
              if hasattr(child, "label")}
    assert {"Kênh", "Thiết bị", "Quốc gia", "Nguồn / medium", "Chiến dịch",
            "Nhóm sản phẩm", "Loại người dùng"} <= labels


def test_none_management_role_restores_the_all_view():
    app = AppTest.from_file(str(APP), default_timeout=60)
    app.session_state["management_role"] = None
    app.run()
    assert len(app.exception) == 0
    assert app.sidebar.segmented_control[0].value == "all"
    assert [item.value for item in app.title] == ["Tổng quan điều hành"]
    assert len(app.sidebar.page_link) == 9


def test_changing_the_role_widget_moves_to_each_role_home():
    app = AppTest.from_file(str(APP), default_timeout=60)
    app.run()
    assert len(app.exception) == 0

    for role in ("manager", "specialist", "cmo", "all"):
        app.sidebar.segmented_control[0].set_value(role)
        app.run()
        title, labels = EXPECTATIONS[role]
        assert len(app.exception) == 0, f"switch to {role} raised an exception"
        assert app.sidebar.segmented_control[0].value == role
        assert [item.value for item in app.title] == [title]
        assert [item.label for item in app.sidebar.page_link] == labels


def _filter_widget(app, label):
    panel = next(panel for panel in app.sidebar.expander if panel.label == "Bộ lọc")
    return next(child for child in panel.children.values() if getattr(child, "label", None) == label)


def test_selected_filters_survive_a_role_change():
    app = AppTest.from_file(str(APP), default_timeout=60)
    app.run()
    assert len(app.exception) == 0

    selected = {}
    for label in ("Nguồn / medium", "Chiến dịch", "Nhóm sản phẩm"):
        widget = _filter_widget(app, label)
        value = [widget.options[0]]
        widget.set_value(value)
        selected[label] = value
    app.run()
    assert len(app.exception) == 0
    for label, value in selected.items():
        assert _filter_widget(app, label).value == value

    app.sidebar.segmented_control[0].set_value("manager")
    app.run()
    assert len(app.exception) == 0
    assert [item.value for item in app.title] == ["So sánh hiệu suất"]
    for label, value in selected.items():
        assert _filter_widget(app, label).value == value
