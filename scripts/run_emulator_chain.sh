#!/usr/bin/env bash
# Compatibility wrapper for the offline Pub/Sub emulator smoke test.
# The canonical orchestrator owns every worker and its resource watchdog.
set -euo pipefail

FIXTURE="${1:-tests/fixtures/ga4_events_sample.jsonl}"
if [ "$#" -gt 0 ]; then shift; fi
OUT_DIR=build/emulator_run

if [ -f .venv/Scripts/python.exe ]; then
  PY=.venv/Scripts/python.exe
elif [ -f .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python3
fi

# The old wrapper used this as a disposable fixture-output directory.
rm -rf "$OUT_DIR"
export REPLAY_OUTPUT_DIR="$OUT_DIR"
bash scripts/run_emulator_replay.sh \
  --from-file "$FIXTURE" --window 5 --timeout 180 "$@"

"$PY" scripts/verify_dry_run.py --dir "$OUT_DIR"
"$PY" scripts/export_quality_log.py --from-jsonl "$OUT_DIR"
echo "[emu] offline fixture chain complete; output: $OUT_DIR"
