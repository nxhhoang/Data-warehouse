#!/usr/bin/env bash
set -euo pipefail

# Resolve python & dbt from the project virtual environment when present,
# otherwise fall back to PATH (e.g. CI or global installs).
if [ -f .venv/Scripts/python.exe ]; then
  PY=.venv/Scripts/python.exe
elif [ -f .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python3
fi
# Absolute path: the script later runs dbt from inside src/warehouse
DBT="$(cd "$(dirname "$PY")" && pwd)/dbt"
command -v "$DBT" >/dev/null 2>&1 || DBT=dbt

# Load .env if present so GCP_PROJECT_ID reaches dbt (env_var) and the KPI deploy
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

echo "[1/5] Compiling channel rules from config/channels.yaml..."
"$PY" scripts/compile_channel_macro.py

echo "[2/5] Checking dbt & BigQuery connectivity..."
cd src/warehouse
"$DBT" debug --profiles-dir .

echo "[3/5] Building all Staging -> Core -> Marts (CTAS)..."
"$DBT" run --full-refresh --profiles-dir .

echo "[4/5] Running quality tests & revenue reconciliation (M3 & M4)..."
"$DBT" test --profiles-dir .

echo "[5/5] Deploying KPI views..."
cd ../..
"$PY" src/kpi/deploy_views.py

echo "Data warehouse & KPI layer rebuild complete!"
