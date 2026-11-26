# GA4 Marketing DSS Warehouse

A small data warehouse and decision-support prototype for GA4 marketing/ecommerce data. It replays historical events locally, loads them into BigQuery Sandbox, builds a star schema with dbt, and exposes the results through Streamlit or Looker Studio CSV snapshots.

This guide is written for someone opening the repository for the first time.

## What the system does

```text
GA4 public data (BigQuery)
  -> Python Publisher (local)
  -> Pub/Sub Emulator (local)
  -> DirectRunner (local)
  -> valid events / dead letters / quality logs (JSONL)
  -> BigQuery Sandbox Raw
  -> Staging views
  -> Core star schema: 4 fact + 8 dimension
  -> 4 marts + 3 KPI views

BigQuery Core/Marts
  -> Streamlit

BigQuery KPI views
  -> CSV export
  -> Looker Studio
```

- **Python Publisher** extracts events by a bounded date range and publishes them chronologically.
- **Pub/Sub Emulator** provides a local queue; no Google Pub/Sub service is required.
- **DirectRunner** validates and normalizes events with Apache Beam, locally.
- **BigQuery Sandbox** stores raw data and runs the dbt warehouse.
- **Streamlit** provides the interactive dashboard implemented in this repository.
- **Looker Studio** can visualize a CSV snapshot exported from the same KPI views.

The current implementation has **4 fact tables and 8 dimension tables**, not 6. Do not remove dimensions just to match an older slide count; dbt models and the dashboard use them.

## Features

- Replay public GA4 ecommerce data locally, without creating a billing account.
- Validate malformed messages, remove duplicates, and record data-quality issues.
- Keep four grains: event, session, purchase item, and item event.
- Aggregate traffic, conversion funnels, revenue, events, and products.
- Filter session KPIs by time, channel, source/medium, campaign, device, country and user type. Product analysis also supports source/medium, campaign and item category; country and user type do not apply to product data.
- Use management tabs for CMO, Manager, and Specialist. These tabs only filter navigation; they are not access control.
- Run manually on Windows, or with Docker on Linux/WSL.
- Guard query sizes, throttle publishing, and track resource usage and process cleanup.

## Prerequisites

Install only what your mode requires.

| Requirement | Offline fixture | BigQuery Sandbox |
|---|---|---|
| Python 3.11 or newer | Required | Required |
| Git Bash (Windows) or Bash | Required | Required |
| JDK for Pub/Sub Emulator | Only emulator mode | Required |
| gcloud CLI with `pubsub-emulator` and `beta` components | Only emulator mode | Required |
| BigQuery Sandbox project | Not required | Required |
| A Google account with ADC | Not required | Required |
| Docker and Docker Compose | Optional | Optional |

Use [BigQuery Sandbox](https://cloud.google.com/bigquery/docs/sandbox) for the cloud warehouse without enabling Cloud Billing. A Google account is needed for that project and credentials. The repository does not need a credit card or a service-account JSON key for the tested flow.

## Installation

### 1. Clone the repository on main

```bash
git clone --branch main --single-branch https://github.com/nxhhoang/Data-warehouse.git
cd Data-warehouse
```

### 2. Create the virtual environment

```bash
bash scripts/setup_venv.sh
```

The script creates `.venv` and installs dependencies from [requirements.txt](./requirements.txt). It does not use system Python for the project.

For PowerShell, activate it before calling tools directly:

```powershell
.venv\Scripts\Activate.ps1
```

### 3. Prepare configuration and credentials

Copy [.env.example](./.env.example) to `.env`, then edit the project entries. Do not commit `.env`.

For local SDK-based emulator usage:

```bash
gcloud components install pubsub-emulator beta
```

BigQuery access needs both CLI authentication and Application Default Credentials (ADC), because these have different purposes:

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_GCP_PROJECT_ID
```

`gcloud auth login` authenticates `gcloud`/`bq`. `gcloud auth application-default login` creates ADC for Python BigQuery clients, dbt, and the Dashboard.

## Configuration

The main variables are:

| Variable | Purpose | Safe example |
|---|---|---|
| `GCP_PROJECT_ID` | Your Sandbox project | `YOUR_GCP_PROJECT_ID` |
| `BQ_QUERY_PROJECT` | Project that executes source queries | Same project |
| `BQ_SOURCE_DATASET` | Public GA4 source | `bigquery-public-data.ga4_obfuscated_sample_ecommerce` |
| `BQ_RAW_PROJECT` | Project owning raw tables | Same project |
| `BQ_RAW_DATASET` / `RAW_DATASET` | Raw dataset | `marketing_dss_raw` |
| `EXTRACT_START_DATE` / `EXTRACT_END_DATE` | Replay window | `2020-11-01` for a smoke test |
| `EXTRACT_LIMIT` | Maximum source events | `100` |
| `PUBLISH_RATE_PER_SEC` | Publish pacing | `10` |
| `REPLAY_BATCH_SIZE` | Raw payload strings per emulator message for bounded replays | `1` |
| `BQ_MAX_QUERY_BYTES` | Per-query guard, in bytes | `134217728` (128 MiB) |
| `BQ_USAGE_LOG` | Local job metrics | `build/bigquery_usage.jsonl` |
| `BQ_MONTHLY_SCAN_BUDGET_GIB` | Self-imposed project warning budget | `50` |
| `DASHBOARD_DATA_SOURCE` | Dashboard input | `mock` or `bigquery` |

`EXTRACT_LIMIT` limits returned rows, not bytes scanned by BigQuery. Keep the date window narrow and read the dry-run estimate before execution.

Only use BigQuery when it is intentional. Local fixture mode uses `GCP_PROJECT_ID=local-project` and `DASHBOARD_DATA_SOURCE=mock`. `local-project` is only an emulator label, not a valid name for BigQuery jobs.

## Run the real flow manually

### 1. Create the raw dataset if missing

Replace `YOUR_GCP_PROJECT_ID` with the same project ID in `.env`:

```powershell
$PROJECT_ID = "YOUR_GCP_PROJECT_ID"
bq mk --dataset --location=US "$PROJECT_ID:marketing_dss_raw"
```

If the dataset already exists, do not delete or recreate it just because `bq mk` reports `Already Exists`. The loader also creates a missing dataset in US.

The default raw table is a daily table. If that table already contains data, the loader refuses to replace it unless you explicitly use `--replace-day`. Prefer a separate test dataset when you do not intend to replace a whole daily table.

### 2. Replay the bounded source batch

Run from the repository root in Git Bash:

```bash
bash scripts/run_emulator_replay.sh --load --timeout 240 --window 5
```

This command manages the emulator, publisher, pipeline, and resource watchdog. The pipeline writes valid events to local JSONL before the loader sends them to BigQuery Raw. It checks child processes while publisher is running, limits that stage with `--publisher-timeout` (1,800 seconds by default), and stops consumers before stopping the emulator. If the pipeline exits early, the script fails instead of waiting for output that cannot arrive.

The default test uses at most 100 events from 2020-11-01. A streaming pipeline appears active while it waits for emulator messages; check its liveness and the resource monitor if the replay seems slow. The separate `--timeout` controls only the wait for output to stabilize after publishing. Before loading raw, the script compares the publisher counters with valid events, dead letters and rows removed by quality rules. A stable file count alone does not prove that replay finished; `build/emulator_replay/replay_counts.json` is written only after accounting matches.

For a bounded large replay, `REPLAY_BATCH_SIZE=64` can reduce emulator message overhead. Each raw payload string is still decoded and processed separately, including malformed records. Also set `BOUNDED_REPLAY=1` when the source size and expected count are known: the bounded collector pulls from the local subscription, persists and flushes a snapshot before acknowledging messages, then stops the emulator before DirectRunner runs on the snapshot. This is a bounded-research replay mode, not a claim about continuously draining a production stream. Use a fresh raw dataset for a new experiment rather than overwriting an older batch.

For an existing raw batch, rebuild only the warehouse and inspect results:

```bash
bash scripts/rebuild_warehouse.sh
python scripts/verify_sandbox.py
python scripts/report_bigquery_usage.py
```

`rebuild_warehouse.sh` creates `src/warehouse/profiles.yml` from its example if needed. dbt uses two threads and inherits the query-size guard from the environment.

### 3. Open Streamlit

Set `DASHBOARD_DATA_SOURCE=bigquery` in `.env` after the warehouse is ready, then run:

```powershell
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
$env:STREAMLIT_SERVER_HEADLESS = "true"
.venv\Scripts\streamlit.exe run src/dashboard/app.py --server.port=8501
```

Open **http://localhost:8501**. Stop the foreground process with `Ctrl+C` when finished.

If you need to stop a leftover replay, use only the managed registrations:

```bash
bash scripts/stop_emulator_replay.sh
python scripts/watch_resources.py --once
```

## Run with Docker

Run these commands from Bash, inside Linux/WSL. The image already contains JDK, gcloud SDK, emulator components, Python dependencies, and the application. Runtime limits are 2 GiB and 1.5 CPU for replay, 1 GiB and 1 CPU for dashboard.

### Offline: fixture and mock dashboard

```bash
GCP_PROJECT_ID=local-project DASHBOARD_DATA_SOURCE=mock PUBLISH_RATE_PER_SEC=0 \
  docker compose up --build
```

The replay fixture runs first, then Streamlit starts on port 8501 with mock data. No Google account is required.

To run only the replay and remove its container automatically:

```bash
GCP_PROJECT_ID=local-project DASHBOARD_DATA_SOURCE=mock PUBLISH_RATE_PER_SEC=0 \
  docker compose run --rm --no-deps replay
```

### Sandbox: real data and warehouse

The bounded collector is optional and is useful when the native streaming consumer cannot be shown to have finished a known batch. It collects and flushes the local snapshot before execution. In this mode, the broker is stopped before the bounded Beam read to release its RAM. Native streaming remains the default for the small fixture.

Mount ADC read-only; never bake credentials into the image. `ADC_FILE` is a Linux/WSL path:

```bash
ADC_FILE=/mnt/c/path/to/application_default_credentials.json \
RAW_DATASET=marketing_dss_docker_tutorial \
  docker compose --env-file .env -f docker-compose.yml \
  -f docker-compose.sandbox.yml up --build
```

For a large bounded replay, also set `BOUNDED_REPLAY=1`, choose a positive extraction limit from the batch metadata, and size the timeout from observed progress. The collector writes the snapshot before Beam runs; it does not turn a failed or partial replay into a warehouse result. This example matches the bounded settings used for the full-day test. Change the raw dataset, date and extraction limit for your own controlled run:

```bash
BOUNDED_REPLAY=1 REPLAY_BATCH_SIZE=64 EXTRACT_LIMIT=56742 \
REPLAY_TIMEOUT_SEC=600 DEDUP_WINDOW_SEC=5 \
ADC_FILE=/mnt/c/path/to/application_default_credentials.json \
RAW_DATASET=marketing_dss_large_yyyymmdd \
  docker compose --env-file .env -f docker-compose.yml \
  -f docker-compose.sandbox.yml up --build
```

The replay service creates/loads the raw batch, builds the warehouse, checks the KPI views, and stops. Dashboard then starts with `DASHBOARD_DATA_SOURCE=bigquery`. Resource limits stay at 2 GiB for replay and 1 GiB for dashboard. The successful full-day run stopped the broker after snapshotting 887 messages, reconciled 56,742 publisher events with the transformed outputs, and loaded 56,741 valid events into a newly created raw table.

Use a fresh dataset name for smoke tests. If the dataset already contains data, the non-empty-day guard stops loading. Use another dataset or explicitly add `REPLACE_RAW_DAY=1` only when replacing that test batch's whole daily table is intended.

Build artifacts go to `build/docker/`, including:

- `build/docker/emulator_replay/output/`
- `build/docker/docker_sandbox_smoke.json`
- `build/docker/bigquery_usage.jsonl`

Finish and clean Compose resources:

```bash
docker compose down --remove-orphans
```

Inspect dashboard health and actual limits after building the Sandbox warehouse:

```bash
ADC_FILE=/mnt/c/path/to/application_default_credentials.json \
  bash scripts/smoke_docker_dashboard.sh
```

The smoke script removes its managed container afterward. The image remains available for the next run.

## Dashboard and Looker Studio

### Interactive dashboard in this repository

Streamlit reads Core/Marts and recomputes KPI ratios from the shared numerator and denominator definitions after filtering. It does not query the three KPI views; those views feed CSV exports for Looker Studio. The dashboard includes overview, performance comparison, channel quality, funnel analysis, drill-down, segmentation, alerts, scenario simulation, and source tracing.

Use shared filters to narrow the analysis. The CMO, Manager, and Specialist tabs only change the available navigation pages; they do not grant or revoke permissions.

### Looker Studio without a BigQuery live connection

Use a CSV snapshot when you want to present the warehouse without configuring a BigQuery Billing Project and direct connector:

1. In BigQuery Console, query each supported KPI view for the intended date range:

   - `v_kpi_traffic_engagement`
   - `v_kpi_funnel`
   - `v_kpi_conversion_revenue`

2. Download the aggregated query results as CSV files.
3. In [Looker Studio](https://lookerstudio.google.com/), create a report and add the CSV files as file-based data sources.
4. Use `event_date` for time, and dimensions such as `channel_group` and `device_category` in charts. Compute ratios from their underlying counts or revenue rather than averaging ratios across groups.

For a reproducible export with the existing per-query guard, use the provided helper rather than repeating the SQL manually:

```bash
python scripts/export_kpi_csv.py --start-date 2020-12-18 \
  --end-date 2020-12-18 --out-dir build/dashboard_exports/20201218
```

It exports all three views with a snapshot limit of 10,000 rows per view, validates required fields and date values, and refuses to overwrite previous snapshots. `manifest.json` records the source, date range and row counts. Use a new output directory for each new experiment. Pair this with an actual render check of Streamlit against the Sandbox data:

```bash
python scripts/smoke_streamlit_sandbox.py --role all \
  --output build/smoke_dashboard_20201218.json
```

A CSV is a **snapshot**, not a live BigQuery connection. Refresh it manually when the warehouse changes. Sandbox resources may expire, so recreating and exporting fresh data may be necessary. These commands do not create or host a report in Looker Studio; upload the exported files there manually.

The optional BigQuery connector has separate billing-project requirements in [Google's connector documentation](https://support.google.com/looker-studio/answer/6370296?hl=en). That is an extension, not a requirement of the local emulator or the CSV presentation flow.

## Test locally and with CI

### No Google account, no billing

```bash
bash scripts/run_simulation.sh
pytest tests -q
```

The simulation uses a nine-line fixture to verify four valid events, two dead letters, and four quality-log rows. The test suite also checks replay overwrite guards, bounded snapshot collection and acknowledgement, managed-process liveness, the three real KPI SQL views and source-item reconciliation, and bounded CSV export. The SQL fixtures use small in-memory SQLite cases with hand-calculated results. These tests need Bash and standard Python dependencies, not BigQuery credentials.

For the full emulator route offline:

```bash
bash scripts/run_emulator_replay.sh \
  --from-file tests/fixtures/ga4_events_sample.jsonl \
  --timeout 240 --window 5
```

### Query-focused checks (Sandbox required)

```bash
python scripts/verify_sandbox.py
python scripts/report_bigquery_usage.py
python tests/benchmark_kpi.py --start-date 20201101 --end-date 20201101
```

The benchmark defaults to the configured extraction date rather than blindly processing all 92 days. Check monthly usage before widening the date range.

Workflow [`.github/workflows/ci-tests.yml`](./.github/workflows/ci-tests.yml) runs local Python/simulation tests and an offline Docker replay. Neither job requires a Google account or Sandbox credentials. Work pushed to your branch triggers these checks. Do not expect them to create BigQuery tables for you.

LaTeX/report PDF generation is handled by the report workflow, not by the commands in this README. For a local change, verify source files and dbt models rather than manually generating a PDF.

## Operational notes

- Check RAM and free disk with `python scripts/watch_resources.py --once`.
- Read the append-only query log at `build/bigquery_usage.jsonl`.
- `report_bigquery_usage.py` uses the current month's project-level BigQuery job metadata. It is an estimate for quota control, not an invoice and may lag the most recent jobs.
- If a replay finish seems slow, check that file writers have flushed/shard output and leave time for windows to stabilize. Do not assume a quota outage without checking BigQuery jobs and the watchdog.
- Do not run multiple replay orchestrators in the same repository at once; they share its PID/output directories.
- Do not publish or display messages by looking inside emulator queues while the pipeline is consuming them. Inspection also pulls/competes for messages.
- Do not use `--replace-day` without understanding that it replaces the complete daily raw table.

## Documentation and useful paths

- [Implementation guide](./GUIDE.md)
- [Script reference](./scripts/README.md)
- [Warehouse models](./src/warehouse)
- [Report source](./report/main.tex)
- [Test suite](./tests)

The report uses **4 facts and 8 dimensions**, four marts, and three KPI views. SQL models include compatible BigQuery type comments such as `-- INT64`, so their output can also be checked manually when drawing the star schema.
