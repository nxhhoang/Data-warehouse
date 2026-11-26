"""Offline checks for bounded BigQuery-to-Looker CSV snapshots."""
import json

import pandas as pd
import pytest

import scripts.export_kpi_csv as exporter


class FrameJob:
    def __init__(self, frame):
        self.frame = frame

    def to_dataframe(self):
        return self.frame.copy()


def _frame(view, size=1):
    required = {
        "v_kpi_traffic_engagement": {"sessions": [483], "users": [90], "engagement_rate": [0.5]},
        "v_kpi_funnel": {"total_sessions": [483], "purchase_completion_rate": [0.75]},
        "v_kpi_conversion_revenue": {
            "orders": [105], "revenue_usd": [6591.0],
            "aov_usd": [62.7714285714], "revenue_share_total": [1.0],
        },
    }
    row = {
        "number": list(range(size)), "event_date": ["2020-12-18"] * size,
        "channel_group": ["Direct"] * size, "device_category": ["desktop"] * size,
    }
    row.update({key: value * size for key, value in required[view].items()})
    return pd.DataFrame(row)


def _patch_queries(monkeypatch, frames):
    calls = []

    def prepare(_, sql, parameters, byte_limit, purpose, usage_log):
        view = sql.split(".kpi.", 1)[1].split("`", 1)[0]
        calls.append({"sql": sql, "parameters": parameters, "bytes": byte_limit,
                      "purpose": purpose, "log": usage_log})
        return FrameJob(frames.get(view, _frame(view)))

    monkeypatch.setattr(exporter, "prepare_query", prepare)
    monkeypatch.setattr(exporter, "record_job", lambda *args: None)
    return calls


def test_exports_each_view_and_preserves_date_and_decimal_formats(tmp_path, monkeypatch):
    calls = _patch_queries(monkeypatch, {})
    summary = exporter.export_snapshots(
        object(), "unit-project", tmp_path / "exports", "20201218", "2020-12-18",
        99_999_999, max_rows=10,
    )
    assert summary["rows_per_view"] == dict.fromkeys(exporter.VIEWS, 1)
    assert len(calls) == 3
    assert all("LIMIT 11" in call["sql"] for call in calls)
    assert all(call["bytes"] == 99_999_999 for call in calls)
    assert all(call["purpose"] == "kpi_snapshot" for call in calls)
    assert [parameter.type_ for call in calls for parameter in call["parameters"]] == ["DATE"] * 6

    for view in exporter.VIEWS:
        output = pd.read_csv(tmp_path / "exports" / f"{view}.csv")
        assert len(output) == 1
        assert output.loc[0, "event_date"] == "2020-12-18"
    revenue = pd.read_csv(tmp_path / "exports" / "v_kpi_conversion_revenue.csv")
    assert revenue.loc[0, "revenue_usd"] == pytest.approx(6591.0)


def test_existing_snapshot_cannot_be_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "v_kpi_funnel.csv"
    path.write_text("keep this snapshot", encoding="utf-8")
    monkeypatch.setattr(exporter, "prepare_query", lambda *_: pytest.fail("query must not run"))
    with pytest.raises(FileExistsError):
        exporter.export_snapshots(
            object(), "project", tmp_path, "20201218", "20201218", 128, 10)
    assert path.read_text(encoding="utf-8") == "keep this snapshot"


def test_exceeding_row_limit_does_not_silently_truncate(tmp_path, monkeypatch):
    calls = _patch_queries(monkeypatch, {"v_kpi_traffic_engagement": _frame(
        "v_kpi_traffic_engagement", size=2)})
    with pytest.raises(ValueError, match="narrow"):
        exporter.export_snapshots(
            object(), "project", tmp_path, "20201218", "20201218", 128, max_rows=1)
    assert len(calls) == 1
    assert not (tmp_path / "manifest.json").exists()
