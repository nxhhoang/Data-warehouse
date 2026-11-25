#!/usr/bin/env bash
# Safely stop all processes registered by run_emulator_replay.sh.
# Useful if a terminal was closed without giving the script's EXIT trap a
# chance to run. Command lines are checked before termination to avoid
# killing an unrelated process whose PID was reused.
set -euo pipefail

if [ -f .venv/Scripts/python.exe ]; then
  PY=.venv/Scripts/python.exe
elif [ -f .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python3
fi

PID_DIR=build/emulator_replay/pids
if [ ! -d "$PID_DIR" ]; then
  echo "No emulator-replay PID registrations found in $PID_DIR"
  exit 0
fi

"$PY" scripts/watch_resources.py --stop-dir "$PID_DIR"
echo "Cleanup complete"
