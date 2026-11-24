"""KPI layer — deploy the KPI views (report section 3.4; step [5/5] of
scripts/rebuild_warehouse.sh).

Reads the CREATE VIEW statements in src/kpi/, substitutes ${PROJECT_ID} with
the real project, creates the kpi dataset if missing, then executes each
statement on BigQuery.
"""

import os
import sys
from pathlib import Path

from google.cloud import bigquery

KPI_DIR = Path(__file__).resolve().parent
REPO_ROOT = KPI_DIR.parents[1]
VIEW_FILES = [
    "v_kpi_traffic_engagement.sql",
    "v_kpi_funnel.sql",
    "v_kpi_conversion_revenue.sql",
]
KPI_DATASET = "kpi"


def load_env_file(path: Path = REPO_ROOT / ".env") -> None:
    """Load key/value pairs from a .env file if it exists; never overwrite."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    """Deploy all KPI views to BigQuery; returns an exit code."""
    load_env_file()
    project_id = os.environ.get("GCP_PROJECT_ID", "")
    if not project_id:
        print("Missing GCP_PROJECT_ID (see .env.example)")
        return 1

    client = bigquery.Client(project=project_id)
    dataset_ref = bigquery.Dataset(f"{project_id}.{KPI_DATASET}")
    try:
        client.get_dataset(dataset_ref)
    except Exception:
        client.create_dataset(dataset_ref)
        print(f"[kpi] created dataset {KPI_DATASET}")

    for filename in VIEW_FILES:
        sql = (KPI_DIR / filename).read_text(encoding="utf-8")
        sql = sql.replace("${PROJECT_ID}", project_id)
        client.query(sql).result()
        print(f"[kpi] deployed {KPI_DATASET}.{filename[:-4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
