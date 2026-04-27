#!/bin/bash

set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-10105}"
FRONTEND_PORT="${FRONTEND_PORT:-4017}"
BACKEND_WORKERS="${BACKEND_WORKERS:-8}"
BACKEND_BIND_HOST="${BACKEND_BIND_HOST:-127.0.0.1}"
BACKEND_PROXY_HOST="${BACKEND_PROXY_HOST:-127.0.0.1}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-6543}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-heym}"
AUTO_REWRITE_LOCAL_DATABASE_HOST="${AUTO_REWRITE_LOCAL_DATABASE_HOST:-true}"

export PLAYWRIGHT_INSTALL_AT_STARTUP="${PLAYWRIGHT_INSTALL_AT_STARTUP:-false}"
export FRONTEND_URL="${FRONTEND_URL:-http://localhost:${FRONTEND_PORT}}"
export CORS_ORIGINS="${CORS_ORIGINS:-${FRONTEND_URL}}"
export PATH="/app/frontend/node_modules/.bin:${PATH}"

is_truthy() {
    case "${1,,}" in
        1|true|yes|on)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

can_resolve_host_docker_internal() {
    python - <<'PY' >/dev/null 2>&1
import socket

socket.gethostbyname("host.docker.internal")
PY
}

build_database_url() {
    printf 'postgresql+asyncpg://%s:%s@%s:%s/%s' \
        "${POSTGRES_USER}" \
        "${POSTGRES_PASSWORD}" \
        "${POSTGRES_HOST}" \
        "${POSTGRES_PORT}" \
        "${POSTGRES_DB}"
}

rewrite_database_url_for_container() {
    DATABASE_URL="${DATABASE_URL:-$(build_database_url)}"

    if ! is_truthy "${AUTO_REWRITE_LOCAL_DATABASE_HOST}"; then
        export DATABASE_URL
        return
    fi

    if ! can_resolve_host_docker_internal; then
        export DATABASE_URL
        return
    fi

    local rewritten_url
    rewritten_url="$(
        python - <<'PY'
import os
from urllib.parse import urlsplit, urlunsplit

url = os.environ["DATABASE_URL"]
parts = urlsplit(url)

if parts.hostname not in {"localhost", "127.0.0.1"}:
    print(url)
    raise SystemExit(0)

userinfo = ""
if parts.username:
    userinfo = parts.username
    if parts.password is not None:
        userinfo += f":{parts.password}"
    userinfo += "@"

port = f":{parts.port}" if parts.port else ""
netloc = f"{userinfo}host.docker.internal{port}"

print(urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)))
PY
    )"

    if [ "${rewritten_url}" != "${DATABASE_URL}" ]; then
        echo "Rewriting database host localhost -> host.docker.internal for container runtime..."
        DATABASE_URL="${rewritten_url}"
    fi

    export DATABASE_URL
}

rewrite_database_url_for_container
export VITE_API_TARGET="${VITE_API_TARGET:-http://${BACKEND_PROXY_HOST}:${BACKEND_PORT}}"

cleanup() {
    if [ -n "${BACKEND_PID:-}" ]; then
        kill "${BACKEND_PID}" 2>/dev/null || true
    fi
    if [ -n "${FRONTEND_PID:-}" ]; then
        kill "${FRONTEND_PID}" 2>/dev/null || true
    fi
    wait "${BACKEND_PID:-}" "${FRONTEND_PID:-}" 2>/dev/null || true
}

trap cleanup SIGINT SIGTERM

echo "Running database migrations..."
cd /app/backend
uv run python -m alembic upgrade head

echo "Starting backend on ${BACKEND_BIND_HOST}:${BACKEND_PORT}..."
uv run python -m uvicorn app.main:app \
    --host "${BACKEND_BIND_HOST}" \
    --port "${BACKEND_PORT}" \
    --workers "${BACKEND_WORKERS}" \
    --proxy-headers \
    --forwarded-allow-ips='*' &
BACKEND_PID=$!

echo "Starting frontend preview on 0.0.0.0:${FRONTEND_PORT}..."
cd /app/frontend
vite preview --host 0.0.0.0 --port "${FRONTEND_PORT}" &
FRONTEND_PID=$!

set +e
wait -n "${BACKEND_PID}" "${FRONTEND_PID}"
STATUS=$?
set -e

cleanup
exit "${STATUS}"
