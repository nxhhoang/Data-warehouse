#!/usr/bin/env bash
# Run the full local simulation chain (no GCP account needed):
#   1. regenerate the GA4-like fixture (9 lines covering every pipeline branch)
#   2. run the Beam pipeline in dry-run mode (DirectRunner, file in / file out)
#   3. verify the routing matches the expected outcome
#   4. export the quality log rows to a CSV under data/quality_log/
# Uses .venv when present; falls back to the system python (e.g. on CI).
set -euo pipefail

if [ -f .venv/Scripts/python.exe ]; then
  PY=.venv/Scripts/python.exe
elif [ -f .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python3
  echo "[sim] no .venv found, using system python"
fi

FIXTURE=tests/fixtures/ga4_events_sample.jsonl
OUT_DIR=build/pipeline_dry_run

echo "[sim 1/4] generating fixture..."
"$PY" scripts/make_test_fixture.py --force

echo "[sim 2/4] running pipeline dry-run..."
rm -rf "$OUT_DIR"
"$PY" src/pipeline/dataflow_pipeline.py \
    --input_file "$FIXTURE" \
    --output_dir "$OUT_DIR" \
    --runner=DirectRunner

echo "[sim 3/4] verifying dry-run outputs..."
"$PY" scripts/verify_dry_run.py --dir "$OUT_DIR"

echo "[sim 4/4] exporting quality log to CSV..."
"$PY" scripts/export_quality_log.py --from-jsonl "$OUT_DIR"

echo "[sim] simulation chain complete"
