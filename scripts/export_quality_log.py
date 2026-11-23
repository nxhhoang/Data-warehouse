"""Export the data quality log to CSV files.

Implements the quality_log section of config/quality_rules.yaml: every
violation recorded by the pipeline (BigQuery table `<raw_dataset>.quality_log`)
or by a local dry-run (JSONL files under build/pipeline_dry_run) is exported
to CSV under data/quality_log/ with the canonical fields
(run_date, rule_name, table, affected_rows, action, detail).

Two sources:
  --from-jsonl DIR   convert dry-run JSONL outputs; no GCP account needed
  (default)          query {project}.{raw_dataset}.quality_log on BigQuery,
                     optionally filtered by --start-date/--end-date

Usage:
    python scripts/export_quality_log.py --from-jsonl build/pipeline_dry_run
    python scripts/export_quality_log.py --start-date 2020-11-01 --end-date 2021-01-31
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["run_date", "rule_name", "table", "affected_rows", "action", "detail"]


def load_from_jsonl(directory: Path) -> list[dict]:
    """Read and merge every quality_log*.jsonl shard written by a dry-run."""
    records = []
    for shard in sorted(directory.glob("quality_log*.jsonl")):
        for line in shard.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_from_bigquery(project_id: str, raw_dataset: str,
                       start_date: str | None, end_date: str | None) -> list[dict]:
    """Query the quality_log table written by the Dataflow pipeline."""
    from google.cloud import bigquery

    query = f"""
        SELECT {", ".join(FIELDS)}
        FROM `{project_id}.{raw_dataset}.quality_log`
    """
    conditions, params = [], []
    if start_date:
        conditions.append("run_date >= @start_date")
        params.append(bigquery.ScalarQueryParameter("start_date", "STRING", start_date))
    if end_date:
        conditions.append("run_date <= @end_date")
        params.append(bigquery.ScalarQueryParameter("end_date", "STRING", end_date))
    if conditions:
        query += "WHERE " + " AND ".join(conditions) + "\n"
    query += "ORDER BY run_date, rule_name"

    job_config = bigquery.QueryJobConfig(query_parameters=params) if params else None
    client = bigquery.Client(project=project_id)
    return [dict(row) for row in client.query(query, job_config=job_config).result()]


def write_csv(records: list[dict], out_dir: Path) -> Path:
    """Write records to a timestamped CSV; returns the file path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"quality_log_{stamp}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field) for field in FIELDS})
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-jsonl", default=None, metavar="DIR",
                        help="dry-run output directory (e.g. build/pipeline_dry_run)")
    parser.add_argument("--out", default=str(REPO_ROOT / "data" / "quality_log"),
                        help="output directory (default data/quality_log/)")
    parser.add_argument("--start-date", default=None, help="BQ mode: first run_date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="BQ mode: last run_date (YYYY-MM-DD)")
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID"),
                        help="BQ mode: GCP project (default env GCP_PROJECT_ID)")
    parser.add_argument("--raw-dataset", default=os.environ.get("RAW_DATASET", "marketing_dss_raw"),
                        help="BQ mode: raw dataset holding the quality_log table")
    args = parser.parse_args()

    if args.from_jsonl:
        source_dir = Path(args.from_jsonl)
        if not source_dir.exists():
            print(f"No such directory: {source_dir}")
            return 1
        records = load_from_jsonl(source_dir)
        source = f"JSONL files in {source_dir}"
    else:
        if not args.project:
            print("Missing GCP_PROJECT_ID for BigQuery mode (see .env.example), "
                  "or use --from-jsonl for local dry-run outputs")
            return 1
        records = load_from_bigquery(args.project, args.raw_dataset,
                                     args.start_date, args.end_date)
        source = f"table {args.project}.{args.raw_dataset}.quality_log"

    if not records:
        print(f"No quality log records found in {source}")
        return 0

    out_path = write_csv(records, Path(args.out))
    summary = Counter(record["rule_name"] for record in records)
    affected = sum(int(record.get("affected_rows") or 0) for record in records)
    print(f"Exported {len(records)} records from {source}")
    print(f"  -> {out_path}")
    print(f"  rows per rule : {dict(summary)}")
    print(f"  affected rows : {affected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
