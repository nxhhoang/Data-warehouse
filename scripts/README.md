# Scripts

Operational scripts for the data warehouse project. Every bash script picks up
the project virtual environment (`.venv`) automatically when it exists and
falls back to the system Python otherwise, so the same scripts work locally
(git-bash on Windows or Linux) and on CI. Unless stated otherwise, run them
from the repository root.

| Script | Layer | Purpose |
|---|---|---|
| `setup_venv.sh` | setup | Create and populate the `.venv` virtual environment |
| `run_simulation.sh` | all (local) | Full simulation chain: fixture → dry-run → verify → quality-log export |
| `run_emulator_chain.sh` | all (local) | Same chain but through the local Pub/Sub emulator (no billing) |
| `run_emulator_replay.sh` | all (local) | Replay real BigQuery or fixture events through the emulator, with resource watchdog |
| `report_bigquery_usage.py` | monitoring | Report per-query and project-month BigQuery usage with a self-imposed budget |
| `verify_sandbox.py` | 4 — Warehouse | Read raw/core metadata and query all three KPI views with a byte limit |
| `smoke_docker_dashboard.sh` | 5 — Dashboard | Probe the dashboard HTTP endpoint and Docker resource limits, then remove the container |
| `stop_emulator_replay.sh` | cleanup | Stop every process registered by the replay orchestrator |
| `watch_resources.py` | monitoring | Track RAM/disk and clean up replay processes |
| `pubsub_status.py` | monitoring | List Pub/Sub resources and safely inspect messages |
| `make_test_fixture.py` | 3 — Transform | Generate the GA4-like JSONL fixture used by the dry-run |
| `rebuild_warehouse.sh` | 3–4 — Transform + Warehouse | Recompile channels, rebuild all dbt models, run tests, deploy KPI views |
| `compile_channel_macro.py` | 4 — Warehouse | Compile `config/channels.yaml` into the `map_channel` dbt macro |
| `verify_dry_run.py` | 3 — Transform | Check dry-run outputs against the expected fixture routing |
| `verify_replay_output.py` | 3 — Transform | Require publisher, valid, dead-letter and dropped-event accounting to match before raw loading |
| `collect_broker_replay.py` | bounded replay | Pull a local bounded subscriber snapshot, flush it, and acknowledge messages with a deadline |
| `export_kpi_csv.py` | 5 — Dashboard | Export bounded KPI-view CSV snapshots for manual Looker Studio upload |
| `smoke_streamlit_sandbox.py` | 5 — Dashboard | Render Streamlit with real BigQuery data and check exceptions/navigation |
| `export_quality_log.py` | quality | Export the quality log (BigQuery table or dry-run JSONL) to CSV |
| `load_raw_to_bigquery.py` | 4 — Warehouse | Upload local pipeline JSONL outputs into BigQuery raw tables (no GCS) |

## setup_venv.sh

Creates `.venv` if missing, upgrades pip and installs `requirements.txt`.
Detects both Windows (`.venv/Scripts`) and Linux (`.venv/bin`) layouts.

```bash
bash scripts/setup_venv.sh
```

Afterwards activate it manually (`source .venv/bin/activate`, or
`.venv\Scripts\Activate.ps1` in PowerShell) — or don't: every other script
finds `.venv` on its own.

## run_simulation.sh

One command for the whole **Level 0** testing strategy (see `docs/runbook.md`):
no GCP account, no billing, no secrets. Chain:

1. `make_test_fixture.py --force` — regenerate the 9-line fixture
2. `dataflow_pipeline.py --input_file ... --output_dir ... --runner=DirectRunner`
3. `verify_dry_run.py` — fail the chain if the routing deviates
4. `export_quality_log.py --from-jsonl` — write `data/quality_log/*.csv`

```bash
bash scripts/run_simulation.sh
```

This is the file-based simulation the Python CI job runs. The separate
`docker-smoke` job exercises `run_emulator_replay.sh --from-file`.

## run_emulator_chain.sh

The **level 4c** chain (see `docs/runbook.md` section 4c): same simulation
flow as `run_simulation.sh`, but the publisher and pipeline talk through the
official Pub/Sub emulator (`gcloud beta emulators pubsub`) instead of files.
Requires the gcloud CLI with the `pubsub-emulator` component and Java 8+.
No billing, no GCP account (the publisher runs in `--from-file` mode).

```bash
gcloud components install pubsub-emulator   # one-time
bash scripts/run_emulator_chain.sh
```

## run_emulator_replay.sh

The canonical orchestrator replays real BigQuery data or an explicit fixture
through the local emulator. It owns the emulator wrapper/Java process,
publisher, pipeline and a RAM/disk watchdog. Native Windows PIDs are resolved
from Git Bash's `WINPID`; Linux emulator processes use a dedicated process group.
Consumers stop before the emulator so cleanup does not create RPC errors.

`EXTRACT_LIMIT` must be positive for BigQuery replay, and
`PUBLISH_RATE_PER_SEC` throttles publishing. The default date range in
`.env.example` is one day, not 92 days. The emulator CLI uses
`--use_bundle_direct_runner` because Prism does not implement Pub/Sub reads.

```bash
bash scripts/run_emulator_replay.sh [--load] [--timeout 240] [--window 5] \
  [--publisher-timeout 1800] [--batch-size 1] \
  [--from-file tests/fixtures/ga4_events_sample.jsonl] [--replace-day]
# --load: upload JSONL to the real raw dataset without GCS.
# --publisher-timeout: cap the extraction/publish stage independently of output settling.
# --batch-size: raw payloads per emulator message; default 1 keeps the original wire format.
# --replace-day: explicitly allow replacing a populated daily table (destructive).
```

Every replay records the publisher's raw-event counters. Before raw loading,
`verify_replay_output.py` checks `valid + dead-letter + quality-dropped`
against those counters. Informational quality rows are not treated as dropped
records. An incomplete count remains bounded by `--timeout`; a count exceeding
input, or another accounting error, blocks the raw load. File sizes staying
stable alone is not accepted as proof that the subscription finished.

For large bounded replays, `REPLAY_BATCH_SIZE=64` (or `--batch-size 64`)
reduces message overhead by packaging unchanged raw payload strings into a
JSON array. The pipeline unpacks and validates each one separately, so a bad
payload still becomes its own dead-letter record. Use a fresh raw dataset for
new experiments instead of relying on overwrite behavior during tests.

### Bounded replay for a known input count

Native streaming via `ReadFromPubSub` remains the default and is exercised by
small fixtures. For a deterministic larger replay, `--bounded-replay` (or
`BOUNDED_REPLAY=1`) adds a bounded broker-to-snapshot phase:

1. `collect_broker_replay.py` pulls only from the local emulator and unpacks
   batches without rewriting the inner raw payloads.
2. It writes a new snapshot, flushes it before ACK, and deduplicates redelivered
   message IDs. It cannot use an old snapshot: the output is created in exclusive
   mode and collection has a deadline.
3. After the publisher's counters and the collected events agree, the owned
   emulator is stopped before DirectRunner reads the bounded file. An externally
   started broker is not stopped by this code.
4. DirectRunner still performs the normal parsing, normalization, quality and
   deduplication work. Raw loading still requires exact accounting from
   `verify_replay_output.py`.

```bash
BOUNDED_REPLAY=1 REPLAY_BATCH_SIZE=64 \
  bash scripts/run_emulator_replay.sh --load --timeout 600 --publisher-timeout 1800
```

This mode is for a known finite test batch. Snapshot ACK is not a claim of
exactly-once distributed delivery or durable production streaming semantics.
Unexpected output counts must still prevent the load; use a fresh raw dataset
when retrying rather than replacing populated data by accident.

`run_emulator_chain.sh` is a compatibility wrapper around this orchestrator for
offline fixtures. It retains `build/emulator_run`, verifies the usual 4/2/4
routing, and exports the quality CSV. Only run one replay orchestrator at a time
in a repository, because its PID registration directory is shared.

## stop_emulator_replay.sh / watch_resources.py

Stops the processes registered by a previous replay, including descendant
Beam workers on Windows (`taskkill /T`). The watchdog reports each process's
RSS and free disk every 15 seconds and can also be invoked once for a manual
status check:

```bash
bash scripts/stop_emulator_replay.sh
python scripts/watch_resources.py --once
```

## pubsub_status.py

Lists the topics and subscriptions in a project; works with the emulator and
with real Pub/Sub. `--peek N --subscription S` inspects messages without ack,
but only use it after stopping the pipeline (peek competes for messages).

```bash
python scripts/pubsub_status.py --project local-project
```

## make_test_fixture.py

Writes a deterministic JSONL fixture that exercises every branch of the
pipeline: valid events, a purchase without `transaction_id`, a purchase with
zero revenue, an exact duplicate, an event without `ga_session_id`,
placeholder values, a malformed JSON line and an event missing `event_date`.

Integers are rendered as strings on purpose — BigQuery `TO_JSON_STRING`
encodes INT64 that way, so the fixture mimics real publisher output.

```bash
python scripts/make_test_fixture.py [--output tests/fixtures/ga4_events_sample.jsonl] [--force]
```

Expected routing (asserted by `verify_dry_run.py`): 4 valid events,
2 dropped purchases, 1 duplicate removed, 2 dead-letter rows, 4 quality-log
rows.

## rebuild_warehouse.sh

Rebuilds the warehouse end to end (the 60-day BigQuery Sandbox table expiry
makes this a routine operation, not a disaster recovery):

1. Compile the channel macro from `config/channels.yaml`
2. `dbt debug --profiles-dir .` (connectivity check)
3. `dbt run --full-refresh` — Staging → Core → Marts via CTAS
4. `dbt test` — quality, parity and reconciliation tests (M3 & M4 acceptance)
5. Deploy the KPI views (`src/kpi/deploy_views.py`)

```bash
bash scripts/rebuild_warehouse.sh
```

Prerequisites: `.env` (or exported `GCP_PROJECT_ID`) and
`gcloud auth application-default login`. If `profiles.yml` is absent, the script
copies the example, with two threads and a per-query byte guard. dbt uses the
extraction start/end dates unless `DBT_VARS` is explicitly set. See `docs/runbook.md`.

`python scripts/report_bigquery_usage.py` aggregates completed query bytes from
`region-us.INFORMATION_SCHEMA.JOBS_BY_PROJECT`. Its default 50 GiB self-imposed
budget is lower than Sandbox's 1 TiB monthly free quota and returns exit code 2
when exhausted. Job history can lag; the local JSONL log is not a billing invoice.

`python scripts/verify_sandbox.py` checks table metadata and executes bounded
`COUNT(*)` on all KPI views. It does not use metrics from the mock dashboard.

## compile_channel_macro.py

Reads `config/channels.yaml` — the single source of truth for channel
grouping — and generates the ordered `CASE` expression into
`src/warehouse/macros/map_channel.sql`. Run it whenever the YAML rules
change; step 1 of `rebuild_warehouse.sh` does this automatically.

```bash
python scripts/compile_channel_macro.py
```

Exits with an error if a rule defines neither `source` nor `medium`
conditions.

## verify_dry_run.py

Reads the JSONL shards written by a dry-run and fails (exit code 1) when the
routing deviates from the expected fixture outcome. Checks: exact counts
(4 valid / 2 dead-letter / 4 quality rows), the set of rule names, the
surviving purchase keeps `AT-001` with an integer `event_timestamp`, and
placeholder `traffic_source` values are nulled.

```bash
python scripts/verify_dry_run.py [--dir build/pipeline_dry_run]
```

## export_quality_log.py

Implements the `quality_log` section of `config/quality_rules.yaml`: exports
recorded violations to a timestamped CSV under `data/quality_log/` with the
canonical fields (`run_date, rule_name, table, affected_rows, action,
detail`) and prints a per-rule summary.

Two sources:

```bash
# From a local dry-run (no GCP account needed)
python scripts/export_quality_log.py --from-jsonl build/pipeline_dry_run

# From the BigQuery table written by the pipeline, filtered by date
python scripts/export_quality_log.py --start-date 2020-11-01 --end-date 2021-01-31
```

Options: `--out` (output directory), `--project` / `--raw-dataset` for the
BigQuery mode (default to `GCP_PROJECT_ID` / `RAW_DATASET` env vars).

## load_raw_to_bigquery.py

Uploads the local pipeline JSONL outputs into the BigQuery raw tables
`events_YYYYMMDD` using client-side load jobs (`load_table_from_file`).
Needs no GCS bucket and works inside the BigQuery Sandbox without billing —
this is the bridge that turns an emulator-chain (or dry-run) output into a
real warehouse build. A non-empty daily table is refused by default to prevent
a small replay from erasing the rest of that day. Only `--replace-day` enables
`WRITE_TRUNCATE` for that table. Extra source fields are ignored so ingestion
matches the smaller raw schema consumed by staging.

```bash
python scripts/load_raw_to_bigquery.py --from-jsonl build/emulator_run
# then point dbt at the raw dataset (BQ_RAW_PROJECT/BQ_RAW_DATASET in .env)
# and run scripts/rebuild_warehouse.sh
```

## KPI CSV and Streamlit sandbox checks

Use `export_kpi_csv.py` to query three real BigQuery KPI views and produce
Looker-compatible snapshots, rather than generating CSV from mock data:

```bash
python scripts/export_kpi_csv.py --project YOUR_GCP_PROJECT_ID \
  --start-date 2020-12-18 --end-date 2020-12-18 \
  --out-dir build/dashboard_exports/20201218
```

Required date headers, row caps (10,000 per view) and byte guards are enforced.
The exporter refuses to overwrite an existing CSV or manifest. `manifest.json`
labels the result as a manual-upload snapshot, not a live BigQuery connector.

`smoke_streamlit_sandbox.py --role all --output build/smoke_dashboard_20201218.json`
runs Streamlit with `DASHBOARD_DATA_SOURCE=bigquery`. It fails on runtime
exceptions, an error block, or failure to render the role's home page. Use
`bash scripts/smoke_docker_dashboard.sh` for the native HTTP health endpoint,
compose limits and cleanup. Files in `build/` are ignored by Git.

## Quota reports, sandbox verification and Docker dashboard

See `GUIDE.md` at the repository root for the complete local/Sandbox replay
commands, including the one-time dataset creation command. These checks all
require real Sandbox credentials and are deliberately not automatic in CI:

```bash
python scripts/report_bigquery_usage.py
python scripts/verify_sandbox.py
python tests/benchmark_kpi.py --start-date 20201101 --end-date 20201101
```

`ADC_FILE=/mnt/c/<path>/application_default_credentials.json \
  bash scripts/smoke_docker_dashboard.sh` checks the containerized dashboard in
WSL. The container is removed by an `EXIT` trap. Offline fixture replay requires
neither a Google account nor credentials.
