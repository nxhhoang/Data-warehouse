#!/usr/bin/env bash
# Smoke-test the Streamlit service against the already-built Sandbox warehouse.
# ADC_FILE must be a Linux/WSL path. The credential is mounted read-only.
set -euo pipefail

NAME=${DASHBOARD_SMOKE_NAME:-ga4-dashboard-smoke}
ADC_FILE=${ADC_FILE:?Set ADC_FILE to application_default_credentials.json}
if [ ! -f "$ADC_FILE" ]; then
  echo "Missing ADC file: $ADC_FILE" >&2
  exit 2
fi
if docker container inspect "$NAME" >/dev/null 2>&1; then
  echo "Refusing to reuse existing container name: $NAME" >&2
  exit 2
fi

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose --env-file .env -f docker-compose.yml -f docker-compose.sandbox.yml \
  run --rm --no-deps --service-ports --detach --name "$NAME" dashboard

READY=0
for _ in $(seq 1 45); do
  if python3 -c 'import urllib.request; raise SystemExit(
      0 if urllib.request.urlopen("http://127.0.0.1:8501/_stcore/health",
                                  timeout=2).status == 200 else 1)' 2>/dev/null; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" -ne 1 ]; then
  docker logs "$NAME"
  echo "Dashboard did not become healthy within 45 seconds" >&2
  exit 1
fi

docker inspect --format \
  'memory_limit={{.HostConfig.Memory}} cpu_nano={{.HostConfig.NanoCpus}} pid_limit={{.HostConfig.PidsLimit}}' \
  "$NAME"
docker stats --no-stream --format 'ram={{.MemUsage}} cpu={{.CPUPerc}}' "$NAME"
python3 -c 'import urllib.request; response = urllib.request.urlopen(
    "http://127.0.0.1:8501", timeout=5); print("dashboard_main_http=", response.status)'
echo "[docker-dashboard] PASS; removing $NAME"
