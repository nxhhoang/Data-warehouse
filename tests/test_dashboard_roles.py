"""Tests for role-based dashboard navigation."""

import pytest

from src.dashboard.roles import PAGE_URLS, allowed_paths, first_page


def test_all_mode_keeps_all_pages_in_order():
    assert allowed_paths("all") == PAGE_URLS


def test_cmo_gets_executive_pages_without_specialist_funnel():
    paths = allowed_paths("cmo")
    assert paths[0] == "tong-quan"
    assert "so-sanh" in paths
    assert "chat-luong-kenh" in paths
    assert "mo-phong" in paths
    assert "pheu" not in paths


def test_manager_gets_operations_pages():
    paths = allowed_paths("manager")
    assert "so-sanh" in paths
    assert "chat-luong-kenh" in paths
    assert "chi-tiet" in paths
    assert "canh-bao" in paths
    assert "mo-phong" in paths
    assert "tong-quan" not in paths


def test_specialist_gets_funnel_segment_and_trace():
    assert allowed_paths("specialist") == ("pheu", "chi-tiet", "phan-khuc", "truy-vet")
    assert first_page("specialist") == "pheu"


def test_unknown_role_is_rejected():
    with pytest.raises(ValueError, match="Unknown management role"):
        allowed_paths("intern")
