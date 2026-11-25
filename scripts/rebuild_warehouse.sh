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
# Use the installed console entrypoint: Windows needs dbt.exe, Linux uses dbt.
if [ -f .venv/Scripts/dbt.exe ]; then
  DBT=.venv/Scripts/dbt.exe
elif [ -x .venv/bin/dbt ]; then
  DBT=.venv/bin/dbt
else
  echo "Missing dbt-bigquery. Run: $PY -m pip install -r requirements.txt"
  exit 1
fi
"$DBT" --version >/dev/null

# Load .env if present so GCP_PROJECT_ID reaches dbt (env_var) and the KPI deploy
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

# Keep dbt on the exact extraction dates unless an explicit override is supplied.
START_DATE=${EXTRACT_START_DATE:-20201101}
END_DATE=${EXTRACT_END_DATE:-$START_DATE}
DBT_VARS=${DBT_VARS:-}
if [ -z "$DBT_VARS" ]; then
  DBT_VARS="{\"start_date\": \"${START_DATE//-/}\", \"end_date\": \"${END_DATE//-/}\"}"
fi

echo "[warehouse] variables: $DBT_VARS"

if [ ! -f src/warehouse/profiles.yml ]; then
  cp src/warehouse/profiles.yml.example src/warehouse/profiles.yml
  echo "[warehouse] Created local profiles.yml from the example."
fi

echo "[1/5] Compiling channel rules from config/channels.yaml..."
"$PY" scripts/compile_channel_macro.py

echo "[2/5] Checking dbt & BigQuery connectivity..."
"$DBT" debug --project-dir src/warehouse --profiles-dir src/warehouse

echo "[3/5] Building all Staging -> Core -> Marts (CTAS)..."
"$DBT" run --full-refresh --project-dir src/warehouse --profiles-dir src/warehouse --vars "$DBT_VARS"

echo "[4/5] Running quality tests & revenue reconciliation (M3 & M4)..."
"$DBT" test --project-dir src/warehouse --profiles-dir src/warehouse --vars "$DBT_VARS"

echo "[5/5] Deploying KPI views..."
"$PY" src/kpi/deploy_views.py

echo "Data warehouse & KPI layer rebuild complete!"
