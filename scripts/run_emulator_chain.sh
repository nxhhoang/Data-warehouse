#!/usr/bin/env bash
# Full streaming chain on the local Pub/Sub emulator — runbook section 4c.
# No billing, no GCP account: the fixture is published to an emulator running
# as a local Java process, and the Beam pipeline consumes it through a real
# subscription (create topic, publish, ack) before writing local JSONL outputs.
#
# Prerequisites (one-time):
#   gcloud CLI + Java 8+ installed, then: gcloud components install pubsub-emulator
#
# Usage:
#   bash scripts/run_emulator_chain.sh [fixture.jsonl]
set -euo pipefail

EMULATOR_PORT=8085
EMULATOR_PROJECT=local-project
FIXTURE="${1:-tests/fixtures/ga4_events_sample.jsonl}"
OUT_DIR=build/emulator_run
# Small window so the test finishes in seconds; the duplicate pair of the
# fixture is published back-to-back and still lands in the same window.
DEDUP_WINDOW_SEC=5

if [ -f .venv/Scripts/python.exe ]; then
  PY=.venv/Scripts/python.exe
elif [ -f .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python3
fi

command -v gcloud >/dev/null 2>&1 || {
  echo "gcloud CLI not found — install it plus 'gcloud components install pubsub-emulator' (runbook section 4c)"
  exit 1
}

echo "[emu 1/4] starting Pub/Sub emulator on localhost:$EMULATOR_PORT..."
gcloud beta emulators pubsub start \
    --project=$EMULATOR_PROJECT --host-port=localhost:$EMULATOR_PORT &
EMULATOR_PID=$!
trap 'kill $EMULATOR_PID 2>/dev/null || true' EXIT

# Wait until the emulator accepts TCP connections (up to 60s)
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

export PUBSUB_EMULATOR_HOST=localhost:$EMULATOR_PORT
export GCP_PROJECT_ID=$EMULATOR_PROJECT

echo "[emu 2/4] publishing fixture to the emulator ($FIXTURE)..."
"$PY" src/extract/publisher.py --from-file "$FIXTURE"

echo "[emu 3/4] running pipeline against the emulator subscription..."
rm -rf "$OUT_DIR"
"$PY" src/pipeline/dataflow_pipeline.py \
    --input_subscription=projects/$EMULATOR_PROJECT/subscriptions/ga4-events-sub \
    --output_dir "$OUT_DIR" \
    --dedup_window_sec $DEDUP_WINDOW_SEC \
    --runner=DirectRunner &
PIPELINE_PID=$!

echo "[emu 4/4] waiting for windows to fire and outputs to land..."
VERIFIED=1
for _ in $(seq 1 24); do
  if "$PY" scripts/verify_dry_run.py --dir "$OUT_DIR" >/dev/null 2>&1; then
    VERIFIED=0
    break
  fi
  sleep 5
done
kill $PIPELINE_PID 2>/dev/null || true
wait $PIPELINE_PID 2>/dev/null || true

if [ "$VERIFIED" -ne 0 ]; then
  echo "FAIL: outputs did not converge to the expected routing within 120s."
  echo "      Known suspects (runbook section 4c):"
  echo "      - Beam<->emulator compatibility: try adding --direct_running_mode=in_memory"
  echo "      - Windows not firing: the watermark can stall when the subscription"
  echo "        goes idle; re-run with a larger fixture or accept file mode"
  exit 1
fi

"$PY" scripts/verify_dry_run.py --dir "$OUT_DIR"
"$PY" scripts/export_quality_log.py --from-jsonl "$OUT_DIR"
echo "[emu] emulator chain complete"
