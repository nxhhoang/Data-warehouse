"""Dashboard settings and shared constants (layer 5).

Settings come from environment variables or the repository .env file
(see .env.example). Values set in the shell always win over the file.
"""

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KPI_DICTIONARY_PATH = REPO_ROOT / "src" / "kpi" / "kpi_dictionary.yaml"

DATA_SOURCES = ("mock", "bigquery")

# Values of core.dim_traffic_source.channel_group, in display order.
# 'Unknown' is the unknown member (key -1) and always sorts last.
CHANNEL_GROUPS = (
    "Direct",
    "Organic Search",
    "Paid Search",
    "Display",
    "Email",
    "Affiliate",
    "Paid Social",
    "Organic Social",
    "Referral",
    "Unknown",
)
DEVICE_CATEGORIES = ("desktop", "mobile", "tablet", "Unknown")

# Dimensions offered by the analysis pages: label -> session frame column
DIMENSIONS = {
    "Kênh": "channel_group",
    "Nguồn / Medium": "source_medium",
    "Chiến dịch": "campaign",
    "Thiết bị": "device_category",
    "Châu lục": "continent",
    "Quốc gia": "country",
    "Loại trang vào": "landing_page_type",
    "Người dùng mới/cũ": "user_type",
    "Mức tương tác": "engagement_level",
}

# Data window of the GA4 sample dataset (dbt vars start_date / end_date).
DATA_START = "2020-11-01"
DATA_END = "2021-01-31"


def load_env_file(path: Path = REPO_ROOT / ".env") -> None:
    """Load key/value pairs from a .env file if it exists; never overwrite."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Strip inline comments such as `EXTRACT_LIMIT=0   # note`
        value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(key.strip(), value)


@dataclass(frozen=True)
class Settings:
    """Runtime settings of the dashboard.

    Parameters
    ----------
    data_source : str
        'mock' (generated data, no GCP needed) or 'bigquery'.
    project_id : str
        GCP project that owns the core / marts / kpi datasets.
    alert_threshold : float
        Default drop threshold for alerts (feature 8); users adjust it in the app.
    """

    data_source: str
    project_id: str
    alert_threshold: float


def get_settings() -> Settings:
    """Read settings from the environment (after loading .env)."""
    load_env_file()
    source = os.environ.get("DASHBOARD_DATA_SOURCE", "mock").strip().lower()
    if source not in DATA_SOURCES:
        raise ValueError(
            f"DASHBOARD_DATA_SOURCE={source!r} is invalid; use one of {DATA_SOURCES}"
        )
    return Settings(
        data_source=source,
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        alert_threshold=float(os.environ.get("ALERT_DEFAULT_THRESHOLD", "0.2")),
    )
