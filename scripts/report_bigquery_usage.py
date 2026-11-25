"""Report project-level BigQuery query usage from authoritative job metadata.

Usage: python scripts/report_bigquery_usage.py --month-budget-gib 50
The INFORMATION_SCHEMA query itself reads only job metadata. It does not replay
GA4 events and is included in the monthly job counts. Billing is not required.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.extract.bigquery_usage import prepare_query, record_job  # noqa: E402
from src.extract.publisher import load_env_file  # noqa: E402


def get_month_usage(client, project, max_query_bytes=128 * 1024**2,
                    usage_log=Path("build/bigquery_usage.jsonl")):
    """Read this calendar month's completed query bytes for the whole project."""
    sql = f"""
        SELECT
            COUNT(*) AS completed_queries,
            COALESCE(SUM(total_bytes_processed), 0) AS bytes_processed,
            COALESCE(SUM(total_bytes_billed), 0) AS bytes_billed
        FROM `{project}.region-us.INFORMATION_SCHEMA.JOBS_BY_PROJECT`
        WHERE job_type = 'QUERY'
          AND state = 'DONE'
          AND creation_time >= TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), MONTH)
    """
    job = prepare_query(client, sql, None, max_query_bytes,
                        "monthly_usage_metadata", usage_log)
    try:
        return dict(next(job.result()))
    finally:
        record_job(job, "monthly_usage_metadata", usage_log)


def append_snapshot(report, path):
    """Persist one monthly project-wide usage snapshot locally."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"report": report}) + "\n")


def main():
    """Print project usage and return 2 when the self-imposed budget is exhausted."""
    load_env_file()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID"))
    parser.add_argument("--month-budget-gib", type=float, default=float(
        os.environ.get("BQ_MONTHLY_SCAN_BUDGET_GIB", "50")))
    parser.add_argument("--usage-log", type=Path, default=Path(
        os.environ.get("BQ_USAGE_LOG", "build/bigquery_usage.jsonl")))
    args = parser.parse_args()
    if not args.project or args.project in ("local-project", "your-project-id"):
        parser.error("Set a real GCP_PROJECT_ID in .env")
    if args.month_budget_gib <= 0:
        parser.error("--month-budget-gib must be positive")

    from google.cloud import bigquery

    client = bigquery.Client(project=args.project)
    max_query_bytes = int(os.environ.get(
        "BQ_MAX_QUERY_BYTES", str(128 * 1024**2)))
    usage = get_month_usage(client, args.project, max_query_bytes, args.usage_log)
    processed = int(usage["bytes_processed"] or 0)
    budget = int(args.month_budget_gib * 1024**3)
    free_tier = 1024**4
    report = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "project": args.project,
        "completed_query_jobs_this_month": int(usage["completed_queries"]),
        "bytes_processed_this_month": processed,
        "gib_processed_this_month": round(processed / 1024**3, 4),
        "self_imposed_budget_gib": args.month_budget_gib,
        "self_imposed_budget_pct": round(100 * processed / budget, 2),
        "estimated_free_tier_remaining_gib": round(
            max(0, free_tier - processed) / 1024**3, 2),
    }
    print(json.dumps(report, indent=2))
    append_snapshot(report, args.usage_log)
    if processed >= budget:
        print("[quota] Self-imposed monthly budget exhausted. Stop and review usage.",
              file=sys.stderr)
        return 2
    print("[quota] Query total includes all completed jobs in this project; "
          "job accounting may lag. Set a small date range and always dry-run first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
