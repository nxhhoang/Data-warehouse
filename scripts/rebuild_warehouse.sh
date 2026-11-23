#!/usr/bin/env bash
set -euo pipefail

echo "[1/5] Bien dich quy tac kenh tu config/channels.yaml..."
python scripts/compile_channel_macro.py

echo "[2/5] Kiem tra ket noi dbt & BigQuery..."
cd src/warehouse
dbt debug

echo "[3/5] Xay dung toan bo Staging -> Core -> Marts (CTAS)..."
dbt run --full-refresh

echo "[4/5] Chay kiem thu chat luong & doi chieu doanh thu (M3 & M4)..."
dbt test

echo "[5/5] Cap nhat he thong KPI Views..."
cd ../..
python src/kpi/deploy_views.py

echo "Hoan tat tai tao Kho du lieu & Tang KPI!"