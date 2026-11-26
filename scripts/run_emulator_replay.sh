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
#       [--publisher-timeout 1800] [--batch-size 1] [--bounded-replay] \
#       [--from-file tests/fixtures/ga4_events_sample.jsonl]
#     --from-file use an offline JSONL fixture instead of querying BigQuery
#     --load      after replay, upload output to the REAL raw dataset on BigQuery
#     --timeout   maximum seconds to wait for stabilized output after publishing (default 1800)
#     --publisher-timeout maximum wall-clock seconds for extraction/publish (default 1800)
#     --batch-size raw event payloads per emulator message; >1 uses a JSON array of payload strings (default 1)
#     --bounded-replay pull a bounded local snapshot before running Beam, for a known input batch only
#     --window    fixed dedup window in seconds (default 600)
# Stop a leftover run manually with: bash scripts/stop_emulator_replay.sh
set -euo pipefail

EMULATOR_PROJECT=local-project
EMULATOR_PORT=8085
RUN_DIR=build/emulator_replay
PID_DIR="$RUN_DIR/pids"
OUT_DIR="${REPLAY_OUTPUT_DIR:-$RUN_DIR/output}"
STATS_FILE="$RUN_DIR/publisher_stats.json"
BROKER_INPUT_FILE="$RUN_DIR/broker_input.jsonl"
TIMEOUT=1800
PUBLISH_TIMEOUT=1800
DEDUP_WINDOW=600
BATCH_SIZE=""
BOUNDED_REPLAY=""
LOAD=0
REPLACE_DAY=0
SOURCE_FILE=""
MONITOR_PID=""
PIPELINE_PID=""
COLLECTOR_PID=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --load) LOAD=1; shift ;;
    --replace-day) REPLACE_DAY=1; shift ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --publisher-timeout) PUBLISH_TIMEOUT="$2"; shift 2 ;;
    --batch-size) BATCH_SIZE="$2"; shift 2 ;;
    --bounded-replay) BOUNDED_REPLAY=1; shift ;;
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

pid_is_running() {
  local expected_pid="$1"
  local running_pid
  [ -n "$expected_pid" ] || return 1
  while read -r running_pid; do
    if [ "$running_pid" = "$expected_pid" ]; then
      return 0
    fi
  done < <(jobs -pr)
  return 1
}

ensure_pipeline_running() {
  if pid_is_running "$PIPELINE_PID"; then
    return 0
  fi
  # Reap the child and fail now instead of waiting for output that cannot arrive.
  local status=0
  wait "$PIPELINE_PID" || status="$?"
  echo "[replay] pipeline stopped during replay (exit=$status); inspect its log." >&2
  return 1
}

start_pipeline() {
  local argument_name="$1"
  local argument_value="$2"
  if [ "$argument_name" = "--input_file" ] && [ "${OS:-}" = "Windows_NT" ]; then
    argument_value="$(cygpath -wa "$argument_value")"
  fi
  "$PY" src/pipeline/dataflow_pipeline.py \
    "${argument_name}=${argument_value}" \
    --output_dir "$PIPELINE_OUT_DIR" \
    --dedup_window_sec "$DEDUP_WINDOW" --use_bundle_direct_runner \
    "${PIPELINE_BATCH_ARGS[@]}" ${PIPELINE_EXTRA_ARGS:-} --runner=DirectRunner &
  PIPELINE_PID=$!
  register_native_pid "$PIPELINE_PID" "pipeline" "dataflow_pipeline.py"
}

wait_for_worker() {
  local worker_pid="$1"
  local label="$2"
  local max_seconds="$3"
  local elapsed=0
  local status=0
  if ! [[ "$max_seconds" =~ ^[1-9][0-9]*$ ]]; then
    echo "[replay] Invalid worker timeout: $max_seconds" >&2
    return 2
  fi
  while pid_is_running "$worker_pid"; do
    if [ "$elapsed" -ge "$max_seconds" ]; then
      echo "[replay] $label exceeded ${max_seconds}s." >&2
      return 1
    fi
    if [ -n "$MONITOR_PID" ] && ! pid_is_running "$MONITOR_PID" 2>/dev/null; then
      echo "[replay] resource watchdog exited; inspect the warnings above." >&2
      return 2
    fi
    if [ "$((elapsed % 30))" -eq 0 ]; then
      "$PY" scripts/watch_resources.py --pid-dir "$PID_DIR" --once || {
        echo "[replay] resource limit violated" >&2; return 2; }
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
  wait "$worker_pid" || status="$?"
  echo "[replay] $label finished with status $status."
  return "$status"
}

ensure_collector_ok() {
  if [ -z "$COLLECTOR_PID" ] || pid_is_running "$COLLECTOR_PID"; then
    return 0
  fi
  local status=0
  wait "$COLLECTOR_PID" || status="$?"
  COLLECTOR_PID=""
  if [ "$status" -ne 0 ]; then
    echo "[replay] broker collector failed with status $status; raw loading was cancelled." >&2
    return 1
  fi
  return 0
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
for bound in "$TIMEOUT" "$PUBLISH_TIMEOUT"; do
  if ! [[ "$bound" =~ ^[1-9][0-9]*$ ]]; then
    echo "[replay] Replay timeouts must be positive integers." >&2
    exit 2
  fi
done
if [ -z "$BATCH_SIZE" ]; then
  BATCH_SIZE="${REPLAY_BATCH_SIZE:-1}"
fi
if ! [[ "$BATCH_SIZE" =~ ^[1-9][0-9]*$ ]]; then
  echo "[replay] Batch size must be a positive integer." >&2
  exit 2
fi
if [ -z "$BOUNDED_REPLAY" ]; then
  BOUNDED_REPLAY="${BOUNDED_REPLAY:-0}"
fi
if [[ "$BOUNDED_REPLAY" != "0" && "$BOUNDED_REPLAY" != "1" ]]; then
  echo "[replay] --bounded-replay and BOUNDED_REPLAY must be 0 or 1." >&2
  exit 2
fi
# Use the same real project identifier for emulator resource names and BigQuery.
# PUBSUB_EMULATOR_HOST ensures all messages stay on the local emulator.
EMULATOR_PROJECT="$GCP_PROJECT_ID"

PUBLISH_ARGS=(--stats-file "$STATS_FILE")
if [ "$BATCH_SIZE" -gt 1 ]; then
  PUBLISH_ARGS+=(--batch-size "$BATCH_SIZE")
fi
PIPELINE_BATCH_ARGS=()
if [ "$BATCH_SIZE" -gt 1 ] || [ "$BOUNDED_REPLAY" -eq 1 ]; then
  PIPELINE_BATCH_ARGS=(--json_batches)
fi
if [ "$BATCH_SIZE" -gt 1 ]; then
  echo "[replay] raw event payload batch size: $BATCH_SIZE"
fi
if [ -n "$SOURCE_FILE" ]; then
  echo "[replay] offline source: $SOURCE_FILE"
  PUBLISH_ARGS+=(--from-file "$SOURCE_FILE")
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

echo "[replay 2/5] starting resource watchdog..."
"$PY" scripts/watch_resources.py --pid-dir "$PID_DIR" --interval 15 &
MONITOR_PID=$!

if [ "$BOUNDED_REPLAY" -eq 1 ]; then
  echo "[replay 2/5] starting bounded broker snapshot collector..."
  "$PY" scripts/collect_broker_replay.py \
    --subscription "projects/$EMULATOR_PROJECT/subscriptions/ga4-events-sub" \
    --stats-file "$STATS_FILE" --out-file "$BROKER_INPUT_FILE" \
    --wait-seconds "$((PUBLISH_TIMEOUT + TIMEOUT))" &
  COLLECTOR_PID=$!
  register_native_pid "$COLLECTOR_PID" "broker-collector" "collect_broker_replay.py"
else
  echo "[replay 2/5] starting streaming pipeline..."
  start_pipeline \
    --input_subscription "projects/$EMULATOR_PROJECT/subscriptions/ga4-events-sub"
fi

if [ -n "$SOURCE_FILE" ]; then
  echo "[replay 3/5] publishing offline fixture events to the emulator..."
else
  echo "[replay 3/5] publishing real BigQuery events to the emulator..."
fi
set +e
"$PY" src/extract/publisher.py "${PUBLISH_ARGS[@]}" &
PUBLISH_PID=$!
register_native_pid "$PUBLISH_PID" "publisher" "publisher.py"
publish_elapsed=0
while pid_is_running "$PUBLISH_PID"; do
  if [ "$publish_elapsed" -ge "$PUBLISH_TIMEOUT" ]; then
    echo "[replay] FAIL: publisher exceeded ${PUBLISH_TIMEOUT}s." >&2
    exit 1
  fi
  if [ "$BOUNDED_REPLAY" -eq 1 ]; then
    ensure_collector_ok || exit 1
  else
    ensure_pipeline_running || exit 1
  fi
  if [ -n "$MONITOR_PID" ] && ! pid_is_running "$MONITOR_PID" 2>/dev/null; then
    echo "[replay] resource watchdog exited; inspect the warnings above." >&2
    exit 2
  fi
  if [ "$((publish_elapsed % 30))" -eq 0 ]; then
    "$PY" scripts/watch_resources.py --pid-dir "$PID_DIR" --once || {
      echo "[replay] resource limit violated" >&2; exit 2; }
  fi
  sleep 5
  publish_elapsed=$((publish_elapsed + 5))
done
wait "$PUBLISH_PID"
PUBLISH_STATUS=$?
set -e
if [ "$PUBLISH_STATUS" -ne 0 ]; then
  echo "[replay] publisher failed with status $PUBLISH_STATUS"
  exit "$PUBLISH_STATUS"
fi
if [ "$BOUNDED_REPLAY" -eq 0 ]; then
  ensure_pipeline_running || exit 1
fi

if [ "$BOUNDED_REPLAY" -eq 1 ]; then
  ensure_collector_ok || exit 1
  if [ -n "$COLLECTOR_PID" ]; then
    echo "[replay 4/5] waiting for the bounded broker snapshot..."
    wait_for_worker "$COLLECTOR_PID" "bounded broker snapshot" "$((PUBLISH_TIMEOUT + TIMEOUT))" || exit 1
    COLLECTOR_PID=""
  fi
  if [ ! -r "$BROKER_INPUT_FILE" ]; then
    echo "[replay] Missing completed broker snapshot; raw loading was cancelled." >&2
    exit 1
  fi
  # The completed snapshot no longer needs the local broker. Free its native
  # process/group before Beam allocates memory; leave externally-owned brokers alone.
  if [ -n "$EMULATOR_PID" ]; then
    "$PY" scripts/watch_resources.py --stop-dir "$PID_DIR" --label-prefix emulator
    echo "[replay] stopped emulator after collecting the complete bounded snapshot."
  fi
  echo "[replay 4/5] running DirectRunner on the bounded snapshot..."
  start_pipeline --input_file "$BROKER_INPUT_FILE"
  wait_for_worker "$PIPELINE_PID" "bounded DirectRunner" "$TIMEOUT" || exit 1
  set +e
  LAST_VALIDATION=$("$PY" scripts/verify_replay_output.py \
    --dir "$OUT_DIR" --stats-file "$STATS_FILE" --output "$RUN_DIR/replay_counts.json")
  validation_status=$?
  set -e
  if [ "$validation_status" -ne 0 ]; then
    printf '%s\n' "$LAST_VALIDATION" >&2
    echo "[replay] bounded replay accounting failed; raw loading was not attempted." >&2
    exit 1
  fi
  printf '%s\n' "$LAST_VALIDATION"
else
  echo "[replay 4/5] waiting for output to stabilize (up to ${TIMEOUT}s)..."
elapsed=0
previous_count=-1
stable_polls=0
LAST_VALIDATION=""
while [ "$elapsed" -lt "$TIMEOUT" ]; do
  "$PY" scripts/watch_resources.py --pid-dir "$PID_DIR" --once || {
    echo "[replay] resource limit violated"; exit 2; }
  ensure_pipeline_running || exit 1
  if ! pid_is_running "$MONITOR_PID" 2>/dev/null; then
    echo "[replay] resource watchdog exited; inspect the warnings above"; exit 2
  fi

  count=$("$PY" - "$OUT_DIR" <<'EOF'
import sys
from pathlib import Path
directory = Path(sys.argv[1])
count = 0
if directory.exists():
    for path in directory.glob("*.jsonl"):
        with path.open(encoding="utf-8") as handle:
            count += sum(1 for line in handle if line.strip())
print(count)
EOF
)
  if [ "$count" -eq "$previous_count" ] && [ "$count" -gt 0 ]; then
    stable_polls=$((stable_polls + 1))
  else
    stable_polls=0
  fi
  if [ "$stable_polls" -ge 3 ]; then
    # Stable file sizes alone cannot prove the subscriber consumed the full input.
    set +e
    LAST_VALIDATION=$("$PY" scripts/verify_replay_output.py \
      --dir "$OUT_DIR" --stats-file "$STATS_FILE" --output "$RUN_DIR/replay_counts.json")
    validation_status=$?
    set -e
    if [ "$validation_status" -eq 0 ]; then
      printf '%s\n' "$LAST_VALIDATION"
      break
    fi
    if [ "$validation_status" -ne 2 ]; then
      printf '%s\n' "$LAST_VALIDATION" >&2
      echo "[replay] replay accounting failed; raw loading was not attempted." >&2
      exit "$validation_status"
    fi
    stable_polls=0
  fi
  previous_count="$count"
  sleep 10
  elapsed=$((elapsed + 10))
done
if [ "$elapsed" -ge "$TIMEOUT" ]; then
  echo "[replay] FAIL: output did not stabilize with complete event accounting within ${TIMEOUT}s" >&2
  if [ -n "$LAST_VALIDATION" ]; then
    printf '%s\n' "$LAST_VALIDATION" >&2
  fi
  echo "       Check pipeline/broker liveness before increasing --timeout." >&2
  exit 1
fi
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
  load_args=(--from-jsonl "$OUT_DIR")
  if [ "$REPLACE_DAY" -eq 1 ]; then
    load_args+=(--replace-day)
  fi
  "$PY" scripts/load_raw_to_bigquery.py "${load_args[@]}"
  echo "[replay] loaded. Point BQ_RAW_* at the raw dataset and rebuild."
else
  echo "[replay 5/5] replay complete. Output: $OUT_DIR"
fi
