"""Verify a small Sandbox warehouse and its three queryable KPI views."""
import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.extract.bigquery_usage import prepare_query, record_job  # noqa: E402
from src.extract.publisher import load_env_file  # noqa: E402

FACTS = ("fct_events", "fct_sessions", "fct_purchase_items", "fct_item_events")
DIMENSIONS = (
    "dim_date", "dim_device", "dim_event", "dim_geo",
    "dim_page", "dim_product", "dim_traffic_source", "dim_user",
)
KPI_VIEWS = ("v_kpi_traffic_engagement", "v_kpi_funnel", "v_kpi_conversion_revenue")


def verify_warehouse(client, project, raw_dataset, raw_date, usage_log):
    """Read table metadata and execute bounded COUNT(*) queries on KPI views."""
    report = {"project": project, "facts": {}, "dimensions": {}, "kpi_views": {}}
    raw = client.get_table(f"{project}.{raw_dataset}.events_{raw_date}")
    report["raw_events"] = raw.num_rows
    for fact in FACTS:
        table = client.get_table(f"{project}.core.{fact}")
        report["facts"][fact] = table.num_rows
    for dimension in DIMENSIONS:
        table = client.get_table(f"{project}.core.{dimension}")
        report["dimensions"][dimension] = table.num_rows
    assert raw.num_rows > 0, "Raw test table is empty"
    assert report["facts"]["fct_events"] == raw.num_rows, "Raw/core event count mismatch"
    assert report["facts"]["fct_sessions"] > 0, "No session rows were built"

    max_query_bytes = int(os.environ.get("BQ_MAX_QUERY_BYTES", str(128 * 1024**2)))
    for view in KPI_VIEWS:
        sql = f"SELECT COUNT(*) AS row_count FROM `{project}.kpi.{view}`"
        job = prepare_query(client, sql, None, max_query_bytes,
                            "sandbox_smoke", usage_log)
        try:
            row = next(job.result())
        finally:
            record_job(job, "sandbox_smoke", usage_log)
        count = int(row.row_count)
        assert count > 0, f"KPI view returned no rows: {view}"
        report["kpi_views"][view] = count
    return report


def main():
    """Verify real project resources using Application Default Credentials."""
    load_env_file()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID"))
    parser.add_argument("--raw-dataset", default=os.environ.get(
        "BQ_RAW_DATASET", "marketing_dss_raw"))
    parser.add_argument("--raw-date", default=os.environ.get(
        "EXTRACT_START_DATE", "20201101").replace("-", ""))
    parser.add_argument("--output", type=Path,
                        default=Path("build/sandbox_smoke_report.json"))
    args = parser.parse_args()
    if not args.project or args.project in ("local-project", "your-project-id"):
        parser.error("Set a real GCP_PROJECT_ID before this Sandbox check")

    from google.cloud import bigquery

    client = bigquery.Client(project=args.project)
    usage_log = os.environ.get("BQ_USAGE_LOG", "build/bigquery_usage.jsonl")
    report = verify_warehouse(
        client, args.project, args.raw_dataset, args.raw_date, usage_log)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"[verify] PASS: raw, 4 facts, {len(DIMENSIONS)} dimensions, 3 KPI views")
    print(f"[verify] Report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
