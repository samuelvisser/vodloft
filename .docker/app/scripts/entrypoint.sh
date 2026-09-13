#!/usr/bin/env bash
set -euo pipefail

mkdir -p /config /downloads
if [[ ! -f "${VODLOFT_CONFIG}" ]]; then
    cp /app/config/config.yml.default "${VODLOFT_CONFIG}"
fi

backend-api db upgrade head
backend-api serve --host 127.0.0.1 --port 8000 &
backend_pid=$!

nginx -g 'daemon off;' &
nginx_pid=$!

shutdown() {
    kill -TERM "$backend_pid" "$nginx_pid" 2>/dev/null || true
    wait "$backend_pid" "$nginx_pid" 2>/dev/null || true
}
trap shutdown EXIT INT TERM

wait -n "$backend_pid" "$nginx_pid"
