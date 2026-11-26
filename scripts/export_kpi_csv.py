"""Export bounded KPI view snapshots for manual upload to Looker Studio.

The script reads real BigQuery KPI views, not mock dashboard data. It applies
both per-query byte and snapshot-row limits, and never overwrites old files.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from src.extract.bigquery_usage import prepare_query, record_job  # noqa: E402
from src.extract.publisher import load_env_file, to_yyyymmdd  # noqa: E402

VIEWS = {
    "v_kpi_traffic_engagement": {"event_date", "channel_group", "device_category",
                                 "sessions", "users", "engagement_rate"},
    "v_kpi_funnel": {"event_date", "channel_group", "device_category",
                     "total_sessions", "purchase_completion_rate"},
    "v_kpi_conversion_revenue": {"event_date", "channel_group", "device_category",
                                 "orders", "revenue_usd", "aov_usd", "revenue_share_total"},
}


def _iso_date(value):
    return datetime.strptime(to_yyyymmdd(value), "%Y%m%d").strftime("%Y-%m-%d")


def export_snapshots(client, project, out_dir, start_date, end_date,
                     max_query_bytes, max_rows=10000, usage_log=None) -> dict:
    """Query all three KPI views and write complete CSV snapshots in both bounds."""
    if not project or max_rows < 1 or max_query_bytes <= 0:
        raise ValueError("A real project, positive row limit and positive byte limit are required")
    start_iso, end_iso = _iso_date(start_date), _iso_date(end_date)
    if start_iso > end_iso:
        raise ValueError("Snapshot start date must not be after end date")
    from google.cloud import bigquery

    out_dir = Path(out_dir)
    output_files = {view: out_dir / f"{view}.csv" for view in VIEWS}
    if any(path.exists() for path in output_files.values()) or (out_dir / "manifest.json").exists():
        raise FileExistsError(f"Snapshot directory already has output files: {out_dir}")

    queries = []
    for view in VIEWS:
        sql = (
            f"SELECT * FROM `{project}.kpi.{view}` "
            "WHERE event_date BETWEEN @start_date AND @end_date "
            f"LIMIT {max_rows + 1}"
        )
        parameters = [
            bigquery.ScalarQueryParameter("start_date", "DATE", start_iso),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_iso),
        ]
        queries.append((view, sql, parameters))

    out_dir.mkdir(parents=True, exist_ok=True)
    exported = {}
    for view, sql, parameters in queries:
        job = prepare_query(
            client, sql, parameters, max_query_bytes, "kpi_snapshot", usage_log)
        try:
            frame = job.to_dataframe()
        finally:
            record_job(job, "kpi_snapshot", usage_log)
        if len(frame) > max_rows:
            raise ValueError(
                f"{view} produced more than {max_rows} rows; narrow the date window")
        if frame.empty:
            raise ValueError(f"{view} returned no rows in the requested date window")
        missing = VIEWS[view] - set(frame.columns)
        if missing:
            raise ValueError(f"{view} is missing expected CSV fields: {sorted(missing)}")
        if frame["event_date"].isna().any():
            raise ValueError(f"{view} contains null event_date values")
        frame["event_date"] = pd.to_datetime(frame["event_date"]).dt.strftime("%Y-%m-%d")
        frame.to_csv(output_files[view], index=False)
        exported[view] = len(frame)

    return {
        "project": project,
        "source": "bigquery_kpi_views",
        "status": "csv_ready_for_manual_looker_upload",
        "start_date": start_iso,
        "end_date": end_iso,
        "max_rows_per_view": max_rows,
        "max_query_bytes": max_query_bytes,
        "rows_per_view": exported,
        "files": {view: str(path) for view, path in output_files.items()},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": "Snapshot only. It does not create or refresh a Looker Studio live BigQuery connection.",
    }


def main() -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID"))
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-rows", type=int, default=10000)
    parser.add_argument("--usage-log", default=os.environ.get(
        "BQ_USAGE_LOG", "build/bigquery_usage.jsonl"))
    args = parser.parse_args()
    if not args.project or args.project in ("local-project", "your-project-id"):
        parser.error("--project must name a real BigQuery Sandbox project")

    from google.cloud import bigquery

    kwargs = {
        "max_query_bytes": int(os.environ.get("BQ_MAX_QUERY_BYTES", 128 * 1024**2)),
        "max_rows": args.max_rows,
        "usage_log": args.usage_log,
    }
    summary = export_snapshots(
        bigquery.Client(project=args.project), args.project, args.out_dir,
        args.start_date, args.end_date or args.start_date, **kwargs)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "manifest.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
