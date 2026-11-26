"""Render the Streamlit dashboard with the real BigQuery Sandbox data source."""
import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

ROLE_HOME_TITLES = {
    "all": "Tổng quan điều hành",
    "cmo": "Tổng quan điều hành",
    "manager": "So sánh hiệu suất",
    "specialist": "Phễu chuyển đổi",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID"))
    parser.add_argument("--role", choices=tuple(ROLE_HOME_TITLES), default="all")
    parser.add_argument("--timeout", type=int, default=120,
                        help="default per-app-run timeout in seconds")
    parser.add_argument("--output", type=Path, required=True,
                        help="local JSON report created only after a successful render")
    args = parser.parse_args()
    if not args.project or args.project in ("local-project", "your-project-id"):
        parser.error("--project must name the BigQuery Sandbox project")
    if args.timeout < 1:
        parser.error("--timeout must be positive")

    os.environ["DASHBOARD_DATA_SOURCE"] = "bigquery"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    app = AppTest.from_file(str(REPO_ROOT / "src" / "dashboard" / "app.py"),
                            default_timeout=args.timeout)
    app.session_state["management_role"] = args.role
    app.run()

    exceptions = [str(exception)[:500] for exception in app.exception]
    if exceptions:
        raise RuntimeError(f"Dashboard exceptions: {exceptions}")
    titles = [item.value for item in app.title]
    expected_title = ROLE_HOME_TITLES[args.role]
    if titles != [expected_title]:
        raise RuntimeError(
            f"Dashboard did not render expected home {expected_title!r}; got {titles}")
    errors = [str(item.value)[:500] for item in app.error]
    if errors:
        raise RuntimeError(f"Dashboard reported data errors: {errors}")

    summary = {
        "status": "PASS",
        "dashboard": "Streamlit",
        "data_source": "bigquery",
        "project": args.project,
        "role": args.role,
        "title": expected_title,
        "sidebar_page_links": len(app.sidebar.page_link),
        "exceptions": 0,
        "note": "AppTest rendered the real Page/Data clients; Looker uses separately exported CSV snapshots.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
