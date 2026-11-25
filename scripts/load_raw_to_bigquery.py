"""Load local pipeline JSONL outputs into BigQuery raw tables (no GCS needed).

The emulator chain (runbook section 4c) ends with JSONL files under a local
output directory. This script uploads them to
<project>.<raw_dataset>.events_YYYYMMDD using client-side load jobs
(load_table_from_file), which work without GCS buckets and inside the
BigQuery Sandbox (no billing). After this, point dbt at the raw dataset
(BQ_RAW_PROJECT / BQ_RAW_DATASET in .env) and run scripts/rebuild_warehouse.sh.

Usage:
    python scripts/load_raw_to_bigquery.py --from-jsonl build/emulator_run
    python scripts/load_raw_to_bigquery.py --from-jsonl build/pipeline_dry_run
"""

import argparse
import io
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.extract.bigquery_usage import record_job  # noqa: E402
from src.extract.publisher import load_env_file  # noqa: E402
from src.pipeline.dataflow_pipeline import RAW_EVENTS_SCHEMA  # noqa: E402


def load_from_jsonl(input_dir: Path, project_id: str, raw_dataset: str,
                    usage_log=Path("build/bigquery_usage.jsonl"),
                    replace_day: bool = False) -> dict:
    """Upload all events*.jsonl shards of a directory into daily raw tables.

    Events are grouped by event_date. WRITE_TRUNCATE rebuilds a daily raw table,
    but a non-empty destination is refused unless replace_day is explicitly True.
    This prevents a small replay from erasing other events in an existing day.

    Parameters
    ----------
    input_dir : Path
        Directory containing events-*.jsonl written by the pipeline.
    project_id : str
        GCP project that owns the raw dataset.
    raw_dataset : str
        Destination dataset (e.g. marketing_dss_raw).
    usage_log : pathlib.Path, optional
        Append-only file for load-job metadata.
    replace_day : bool, optional
        Whether Write Truncate may replace a non-empty daily table. Default is False.

    Returns
    -------
    dict
        Mapping of table id -> number of loaded events.
    """
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    dataset_ref = bigquery.Dataset(f"{project_id}.{raw_dataset}")
    dataset_ref.location = "US"
    try:
        client.get_dataset(dataset_ref)
    except NotFound:
        client.create_dataset(dataset_ref)
        print(f"[load] created dataset {raw_dataset} in US")
    schema = [bigquery.SchemaField.from_api_repr(field)
              for field in RAW_EVENTS_SCHEMA["fields"]]

    by_date = defaultdict(list)
    for shard in sorted(input_dir.glob("events*.jsonl")):
        for line in shard.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                event = json.loads(line)
                by_date[event["event_date"]].append(line)

    if not by_date:
        raise SystemExit(f"No events found under {input_dir}")

    stats = {}
    for event_date, lines in sorted(by_date.items()):
        table_id = f"{project_id}.{raw_dataset}.events_{event_date}"
        try:
            existing = client.get_table(table_id)
        except NotFound:
            existing = None
        if existing is not None and existing.num_rows and not replace_day:
            raise RuntimeError(
                f"Refusing to replace {table_id}: it already has {existing.num_rows} rows. "
                "Use a separate RAW_DATASET or explicitly pass --replace-day."
            )
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            schema=schema,
            # GA4 exports extra top-level/nested fields. The pipeline's raw
            # schema intentionally keeps only what staging consumes.
            ignore_unknown_values=True,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        job = client.load_table_from_file(io.BytesIO(payload), table_id,
                                             job_config=job_config)
        try:
            job.result()
        finally:
            record_job(job, "raw_load", usage_log)
        stats[table_id] = len(lines)
        print(f"[load] {table_id}: {len(lines)} events")
    return stats


def main() -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-jsonl", required=True, metavar="DIR",
                        help="pipeline output directory (e.g. build/emulator_run)")
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID"),
                        help="GCP project (default env GCP_PROJECT_ID)")
    parser.add_argument("--raw-dataset", default=os.environ.get("RAW_DATASET", "marketing_dss_raw"),
                        help="destination raw dataset")
    parser.add_argument("--replace-day", action="store_true",
                        help="allow replacing a non-empty daily table (destructive)")
    args = parser.parse_args()

    input_dir = Path(args.from_jsonl)
    if not input_dir.exists():
        print(f"No such directory: {input_dir}")
        return 1
    if not args.project:
        print("Missing GCP_PROJECT_ID (see .env.example)")
        return 1

    load_from_jsonl(input_dir, args.project, args.raw_dataset,
                    usage_log=os.environ.get(
                        "BQ_USAGE_LOG", "build/bigquery_usage.jsonl"),
                    replace_day=args.replace_day)
    print("[load] done — point dbt at the raw dataset and rebuild the warehouse")
    return 0


if __name__ == "__main__":
    sys.exit(main())
