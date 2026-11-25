"""BigQuery query guards and append-only usage records for free-tier tests.

Every recorded query has a dry-run estimate before execution. The estimate must
fit the per-query budget and the executed job also has a maximum_bytes_billed
limit. Actual job metrics, not merely dry-run estimates, are retained locally.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_USAGE_LOG = Path("build/bigquery_usage.jsonl")


def record_job(job, purpose, path=DEFAULT_USAGE_LOG):
    """Append resource metrics for a finished BigQuery job.

    Parameters
    ----------
    job : google.cloud.bigquery.job.QueryJob or LoadJob
        Job whose metadata should be retained without the source SQL.
    purpose : str
        Logical stage, such as source_extract, dashboard or raw_load.
    path : pathlib.Path, optional
        Append-only JSONL destination; ignored when set to None.
    """
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "purpose": purpose,
        "dry_run": bool(getattr(job, "dry_run", False)),
        "job_id": getattr(job, "job_id", None),
        "job_type": getattr(job, "job_type", None),
        "location": getattr(job, "location", None),
        "cache_hit": bool(getattr(job, "cache_hit", False)),
        "total_bytes_processed": int(getattr(job, "total_bytes_processed", None) or 0),
        "total_bytes_billed": int(getattr(job, "total_bytes_billed", None) or 0),
        "output_rows": getattr(job, "num_dml_affected_rows", None),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def prepare_query(client, query, parameters, maximum_bytes_billed, purpose,
                  usage_log=DEFAULT_USAGE_LOG, use_query_cache=True):
    """Dry-run a query, enforce its scan budget and return the real job.

    A failed dry-run stops execution instead of falling back to an unbounded
    query. The caller must consume job.result(), then call record_job().

    Parameters
    ----------
    client : google.cloud.bigquery.Client
        BigQuery client authenticated for the project executing the job.
    query : str
        SQL to validate and execute.
    parameters : list, optional
        BigQuery scalar or array query parameters.
    maximum_bytes_billed : int
        Positive per-query ceiling in bytes, enforced both before and at execution.
    purpose : str
        Name of the pipeline stage written into the usage log.
    usage_log : pathlib.Path, optional
        Append-only metrics file. Default is build/bigquery_usage.jsonl.
    use_query_cache : bool, optional
        Whether the executed query can reuse BigQuery's result cache.

    Returns
    -------
    google.cloud.bigquery.job.QueryJob
        Started query job; the caller still needs to consume its result.

    Raises
    ------
    ValueError
        If the byte ceiling is not positive or the dry-run estimate exceeds it.
    """
    from google.cloud import bigquery

    maximum_bytes_billed = int(maximum_bytes_billed)
    if maximum_bytes_billed <= 0:
        raise ValueError("BigQuery query guard requires a positive byte limit")
    dry_config = bigquery.QueryJobConfig(
        dry_run=True, use_query_cache=False, query_parameters=parameters or [])
    dry_job = client.query(query, job_config=dry_config)
    record_job(dry_job, f"{purpose}_dry_run", usage_log)
    estimate = int(dry_job.total_bytes_processed or 0)
    print(f"[quota] {purpose}: dry-run estimate={estimate / 1024**2:.2f} MiB; "
          f"limit={maximum_bytes_billed / 1024**2:.2f} MiB", flush=True)
    if estimate > maximum_bytes_billed:
        raise ValueError(
            f"Query needs approximately {estimate / 1024**2:.2f} MiB, above the "
            f"{maximum_bytes_billed / 1024**2:.2f} MiB limit. Narrow the date "
            "range or explicitly increase the limit after checking monthly usage."
        )
    config = bigquery.QueryJobConfig(
        query_parameters=parameters or [],
        maximum_bytes_billed=maximum_bytes_billed,
        use_query_cache=use_query_cache,
    )
    return client.query(query, job_config=config)
