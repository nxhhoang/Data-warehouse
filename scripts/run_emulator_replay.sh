#!/usr/bin/env bash
# Variant 4c/B: replay real GA4 data through the local Pub/Sub emulator.
#
# Processes managed by this script (all are killed on every exit path):
#   - Pub/Sub emulator (gcloud + Java), PID registered in the run directory
#   - Beam pipeline, streaming from the emulator subscription
#   - publisher.py, querying BigQuery in the foreground
#   - watch_resources.py, reporting RAM and free disk every 15 seconds
#
# PUBLISH_RATE_PER_SEC in .env controls replay pacing. Pipeline concurrency can
# be lowered with PIPELINE_EXTRA_ARGS="--direct_num_workers=1".
#
# Prerequisites: gcloud CLI + Java 8+, `gcloud components install pubsub-emulator`,
# .env and ADC credentials for the real BigQuery data source.
#
# Usage:
#   bash scripts/run_emulator_replay.sh [--load] [--timeout 1800] [--window 600] \
#       [--from-file tests/fixtures/ga4_events_sample.jsonl]
#     --from-file use an offline JSONL fixture instead of querying BigQuery
#     --load      after replay, upload output to the REAL raw dataset on BigQuery
#     --timeout   maximum seconds to wait for stabilized output (default 1800)
#     --window    fixed dedup window in seconds (default 600)
# Stop a leftover run manually with: bash scripts/stop_emulator_replay.sh
set -euo pipefail

EMULATOR_PROJECT=local-project
EMULATOR_PORT=8085
RUN_DIR=build/emulator_replay
PID_DIR="$RUN_DIR/pids"
OUT_DIR="${REPLAY_OUTPUT_DIR:-$RUN_DIR/output}"
TIMEOUT=1800
DEDUP_WINDOW=600
LOAD=0
REPLACE_DAY=0
SOURCE_FILE=""
MONITOR_PID=""
PIPELINE_PID=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --load) LOAD=1; shift ;;
    --replace-day) REPLACE_DAY=1; shift ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --window) DEDUP_WINDOW="$2"; shift 2 ;;
    --from-file) SOURCE_FILE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 2 ;;
  esac
done

if [ -f .venv/Scripts/python.exe ]; then
  PY=.venv/Scripts/python.exe
elif [ -f .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python3
fi

register_pid() {
  printf '{"pid": %s, "label": "%s", "token": "%s"}\n' "$1" "$2" "$3" > "$PID_DIR/$2.json"
}

register_native_pid() {
  local native_pid="$1"
  if [ "${OS:-}" = "Windows_NT" ]; then
    # ps without -o returns PID PPID PGID WINPID for a Git-Bash child.
    native_pid=$(ps -p "$1" | awk 'NR == 2 {print $4}')
  fi
  if ! [[ "$native_pid" =~ ^[0-9]+$ ]]; then
    echo "Cannot resolve native Windows PID for $2" >&2
    return 1
  fi
  register_pid "$native_pid" "$2" "$3"
}

cleanup() {
  status=$?
  if [ -n "$MONITOR_PID" ]; then kill "$MONITOR_PID" 2>/dev/null || true; fi
  if [ -d "$PID_DIR" ]; then
    "$PY" scripts/watch_resources.py --stop-dir "$PID_DIR" || true
  fi
  return "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

command -v gcloud >/dev/null 2>&1 || {
  echo "gcloud CLI not found (see runbook section 4c prerequisites)"; exit 1; }

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
if [ -n "$SOURCE_FILE" ] && [ ! -f "$SOURCE_FILE" ]; then
  echo "[replay] Missing source fixture: $SOURCE_FILE"
  exit 1
fi
if [ -z "$SOURCE_FILE" ]; then
  if [ -z "${GCP_PROJECT_ID:-}" ] || [ "$GCP_PROJECT_ID" = "local-project" ] \
          || [ "$GCP_PROJECT_ID" = "your-project-id" ]; then
    echo "[replay] Set a real GCP_PROJECT_ID in .env before replaying BigQuery data."
    exit 1
  fi
fi
export GCP_PROJECT_ID="${GCP_PROJECT_ID:-local-project}"
if [ -z "$SOURCE_FILE" ] && [ "${EXTRACT_LIMIT:-0}" -le 0 ]; then
  echo "[replay] Sandbox tests require a positive EXTRACT_LIMIT."
  exit 1
fi
# Use the same real project identifier for emulator resource names and BigQuery.
# PUBSUB_EMULATOR_HOST ensures all messages stay on the local emulator.
EMULATOR_PROJECT="$GCP_PROJECT_ID"

PUBLISH_ARGS=()
if [ -n "$SOURCE_FILE" ]; then
  echo "[replay] offline source: $SOURCE_FILE"
  PUBLISH_ARGS=(--from-file "$SOURCE_FILE")
else
  echo "[replay] EXTRACT_LIMIT=$EXTRACT_LIMIT events per day range"
fi

# Clean up registrations left by a previous run before starting new children.
if [ -d "$PID_DIR" ]; then
  "$PY" scripts/watch_resources.py --stop-dir "$PID_DIR" || true
fi
rm -rf "$RUN_DIR"
mkdir -p "$PID_DIR"

if [ "${EMULATOR_PRESTARTED:-0}" = "1" ]; then
  echo "[replay 1/5] using emulator already listening on localhost:$EMULATOR_PORT..."
  EMULATOR_PID=""
else
  echo "[replay 1/5] starting emulator..."
  if [ "${OS:-}" = "Windows_NT" ]; then
    gcloud beta emulators pubsub start \
        --project="$EMULATOR_PROJECT" --host-port="localhost:$EMULATOR_PORT" &
    EMULATOR_PID=$!
    # Register the native wrapper before probing so failed startup also cleans up.
    register_native_pid "$EMULATOR_PID" "emulator-wrapper" "pubsub"
  else
    setsid gcloud beta emulators pubsub start \
        --project="$EMULATOR_PROJECT" --host-port="localhost:$EMULATOR_PORT" &
    EMULATOR_PID=$!
    register_pid "$EMULATOR_PID" "emulator" "pubsub"
  fi
fi

"$PY" - "$EMULATOR_PORT" <<'EOF'
import socket
import sys
import time

port = int(sys.argv[1])
for _ in range(60):
    try:
        socket.create_connection(("localhost", port), timeout=1).close()
        sys.exit(0)
    except OSError:
        time.sleep(1)
sys.exit("emulator did not accept connections within 60s")
EOF

export PUBSUB_EMULATOR_HOST="localhost:$EMULATOR_PORT"

if [ "${OS:-}" = "Windows_NT" ] && [ "${EMULATOR_PRESTARTED:-0}" != "1" ]; then
  "$PY" scripts/watch_resources.py --pid-dir "$PID_DIR" \
      --register-listener "$EMULATOR_PORT" --token cloud-pubsub-emulator
fi

echo "[replay] preparing topic and subscription before starting consumer..."
GCP_PROJECT_ID="$EMULATOR_PROJECT" "$PY" src/extract/publisher.py --setup-only

PIPELINE_OUT_DIR="$OUT_DIR"
if [ "${OS:-}" = "Windows_NT" ]; then
  PIPELINE_OUT_DIR="$(cygpath -wa "$OUT_DIR")"
fi

echo "[replay 2/5] starting resource watchdog and streaming pipeline..."
"$PY" scripts/watch_resources.py --pid-dir "$PID_DIR" --interval 15 &
MONITOR_PID=$!

"$PY" src/pipeline/dataflow_pipeline.py \
    --input_subscription="projects/$EMULATOR_PROJECT/subscriptions/ga4-events-sub" \
    --output_dir "$PIPELINE_OUT_DIR" \
    --dedup_window_sec "$DEDUP_WINDOW" --use_bundle_direct_runner \
    ${PIPELINE_EXTRA_ARGS:-} --runner=DirectRunner &
PIPELINE_PID=$!
register_native_pid "$PIPELINE_PID" "pipeline" "dataflow_pipeline.py"

if [ -n "$SOURCE_FILE" ]; then
  echo "[replay 3/5] publishing offline fixture events to the emulator..."
else
  echo "[replay 3/5] publishing real BigQuery events to the emulator..."
fi
set +e
"$PY" src/extract/publisher.py "${PUBLISH_ARGS[@]}" &
PUBLISH_PID=$!
register_native_pid "$PUBLISH_PID" "publisher" "publisher.py"
wait "$PUBLISH_PID"
PUBLISH_STATUS=$?
set -e
if [ "$PUBLISH_STATUS" -ne 0 ]; then
  echo "[replay] publisher failed with status $PUBLISH_STATUS"
  exit "$PUBLISH_STATUS"
fi

echo "[replay 4/5] waiting for output to stabilize (up to ${TIMEOUT}s)..."
elapsed=0
previous_count=-1
stable_polls=0
while [ "$elapsed" -lt "$TIMEOUT" ]; do
  "$PY" scripts/watch_resources.py --pid-dir "$PID_DIR" --once || {
    echo "[replay] resource limit violated"; exit 2; }
  if ! kill -0 "$MONITOR_PID" 2>/dev/null; then
    echo "[replay] resource watchdog exited; inspect the warnings above"; exit 2
  fi

  count=$("$PY" - "$OUT_DIR" <<'EOF'
import sys
from pathlib import Path
directory = Path(sys.argv[1])
if not directory.exists():
    print(0)
else:
    print(sum(len(path.read_text(encoding="utf-8").splitlines())
              for path in directory.glob("*.jsonl")))
EOF
)
  if [ "$count" -eq "$previous_count" ] && [ "$count" -gt 0 ]; then
    stable_polls=$((stable_polls + 1))
  else
    stable_polls=0
  fi
  if [ "$stable_polls" -ge 3 ]; then
    echo "[replay] output stable at $count lines after ${elapsed}s"
    break
  fi
  previous_count="$count"
  sleep 10
  elapsed=$((elapsed + 10))
done
if [ "$elapsed" -ge "$TIMEOUT" ]; then
  echo "[replay] FAIL: output did not stabilize within ${TIMEOUT}s"
  echo "       Try --direct_running_mode=in_memory or a larger --timeout."
  exit 1
fi

# Stop all managed children before uploading/finishing. The EXIT trap repeats
# this safely, so every normal, error and signal path cleans up.
if [ -n "$MONITOR_PID" ]; then kill "$MONITOR_PID" 2>/dev/null || true; MONITOR_PID=""; fi
"$PY" scripts/watch_resources.py --stop-dir "$PID_DIR"

if [ "$LOAD" -eq 1 ]; then
  echo "[replay 5/5] loading output into the real raw dataset..."
  if [ -z "${GCP_PROJECT_ID:-}" ]; then
    echo "Missing real GCP_PROJECT_ID in .env for --load"; exit 1
  fi
  "$PY" scripts/load_raw_to_bigquery.py --from-jsonl "$OUT_DIR" \
      ${REPLACE_DAY:+--replace-day}
  echo "[replay] loaded. Point BQ_RAW_* at the raw dataset and rebuild."
else
  echo "[replay 5/5] replay complete. Output: $OUT_DIR"
fi
