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
| `make_test_fixture.py` | 3 — Transform | Generate the GA4-like JSONL fixture used by the dry-run |
| `rebuild_warehouse.sh` | 3–4 — Transform + Warehouse | Recompile channels, rebuild all dbt models, run tests, deploy KPI views |
| `compile_channel_macro.py` | 4 — Warehouse | Compile `config/channels.yaml` into the `map_channel` dbt macro |
| `verify_dry_run.py` | 3 — Transform | Check dry-run outputs against the expected fixture routing |
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

This is the exact chain the GitHub Actions workflow
(`ci-tests.yml`) runs on every branch after the unit tests.

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

Prerequisites: `.env` (or exported `GCP_PROJECT_ID`),
`src/warehouse/profiles.yml` copied from `profiles.yml.example`, and
`gcloud auth application-default login`. See `docs/runbook.md` section 4.

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
real warehouse build. Each day is loaded with `WRITE_TRUNCATE`, so re-running
the chain and this script is idempotent per day.

```bash
python scripts/load_raw_to_bigquery.py --from-jsonl build/emulator_run
# then point dbt at the raw dataset (BQ_RAW_PROJECT/BQ_RAW_DATASET in .env)
# and run scripts/rebuild_warehouse.sh
```
