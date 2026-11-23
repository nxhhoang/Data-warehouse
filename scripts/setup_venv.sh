#!/usr/bin/env bash
# Create/populate the project virtual environment (.venv).
# Works in git-bash on Windows (.venv/Scripts) and Linux/WSL (.venv/bin).
set -euo pipefail

if [ ! -d .venv ]; then
  echo "[setup] creating .venv..."
  python3 -m venv .venv
fi

if [ -f .venv/Scripts/python.exe ]; then
  PY=.venv/Scripts/python.exe
else
  PY=.venv/bin/python
fi

echo "[setup] upgrading pip..."
"$PY" -m pip install --upgrade pip

echo "[setup] installing requirements.txt..."
"$PY" -m pip install -r requirements.txt

echo "[setup] done. Activate with:"
if [ -f .venv/Scripts/python.exe ]; then
  echo "  source .venv/Scripts/activate   (git-bash)  or  .\\.venv\\Scripts\\Activate.ps1   (PowerShell)"
else
  echo "  source .venv/bin/activate"
fi
