#!/usr/bin/env bash
# One container contains the local broker and worker; BigQuery stays external.
# Local fixture mode is the default. Cloud ingestion and dbt are explicit opt-ins.
set -euo pipefail

MODE=${1:-replay}
export PYTHONUNBUFFERED=1
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
export STREAMLIT_SERVER_HEADLESS=true

if [ "$MODE" = "dashboard" ]; then
  exec .venv/bin/streamlit run src/dashboard/app.py \
    --server.address=0.0.0.0 \
    --server.port="${DASHBOARD_PORT:-8501}" \
    --server.headless=true \
    --browser.gatherUsageStats=false
fi

if [ "$MODE" != "replay" ]; then
  echo "Usage: {replay|dashboard}" >&2
  exit 2
fi

if [ "${LOAD_RAW:-0}" = "1" ] || [ "${BUILD_WAREHOUSE:-0}" = "1" ]; then
  if [ -z "${GCP_PROJECT_ID:-}" ] || [ "$GCP_PROJECT_ID" = "local-project" ] \
      || [ "$GCP_PROJECT_ID" = "your-project-id" ]; then
    echo "Cloud loading requires a real GCP_PROJECT_ID; keep local-project for fixture tests." >&2
    exit 2
  fi
fi

args=(--timeout "${REPLAY_TIMEOUT_SEC:-240}" --window "${DEDUP_WINDOW_SEC:-5}"
      --batch-size "${REPLAY_BATCH_SIZE:-1}")
if [ "${BOUNDED_REPLAY:-0}" = "1" ]; then
  args+=(--bounded-replay)
fi
if [ -n "${REPLAY_SOURCE_FILE:-}" ]; then
  args+=(--from-file "$REPLAY_SOURCE_FILE")
fi
if [ "${LOAD_RAW:-0}" = "1" ]; then
  args+=(--load)
fi
if [ "${REPLACE_RAW_DAY:-0}" = "1" ]; then
  args+=(--replace-day)
fi

bash scripts/run_emulator_replay.sh "${args[@]}"

if [ -n "${REPLAY_SOURCE_FILE:-}" ] && [ "${VERIFY_FIXTURE_OUTPUT:-1}" = "1" ]; then
  .venv/bin/python scripts/verify_dry_run.py --dir build/emulator_replay/output
fi

if [ "${BUILD_WAREHOUSE:-0}" = "1" ]; then
  bash scripts/rebuild_warehouse.sh
  .venv/bin/python scripts/verify_sandbox.py --output build/docker_sandbox_smoke.json
fi

if [ "${LOAD_RAW:-0}" = "1" ]; then
  .venv/bin/python scripts/report_bigquery_usage.py
fi

echo "[docker] replay completed; worker/emulator processes have stopped."
