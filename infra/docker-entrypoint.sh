#!/bin/sh
set -eu

mkdir -p /data/browser_profiles /data/logs /data/config

exec python -m uvicorn apps.api.main:app \
  --host "${API_HOST:-0.0.0.0}" \
  --port "${API_PORT:-8001}" \
  --proxy-headers
