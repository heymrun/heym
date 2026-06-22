#!/bin/sh

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN_ID="${E2E_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
CONTAINER_NAME="heym-e2e-postgres-$$"
ARTIFACT_DIR="${E2E_ARTIFACT_DIR:-.e2e-artifacts/${RUN_ID}}"

find_free_port() {
    start_port="$1"
    python3 - "$start_port" <<'PY'
import socket
import sys

start = int(sys.argv[1])
for port in range(start, min(start + 1000, 65536)):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            continue
    print(port)
    break
else:
    raise SystemExit(f"No free port found from {start}")
PY
}

FRONTEND_PORT="${E2E_FRONTEND_PORT:-$(find_free_port "$((20000 + ($$ % 10000)))")}"
BACKEND_PORT="${E2E_BACKEND_PORT:-$(find_free_port "$((30000 + ($$ % 10000)))")}"

cleanup() {
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if ! docker info >/dev/null 2>&1; then
    echo "Docker daemon is not running. Start Docker Desktop and retry ./run_e2e.sh."
    exit 1
fi

if [ -n "${E2E_POSTGRES_PORT:-}" ]; then
    echo "Starting isolated E2E PostgreSQL on port ${E2E_POSTGRES_PORT}..."
    docker run --rm -d \
        --name "$CONTAINER_NAME" \
        -e POSTGRES_USER=postgres \
        -e POSTGRES_PASSWORD=postgres \
        -e POSTGRES_DB=heym_e2e \
        -p "127.0.0.1:${E2E_POSTGRES_PORT}:5432" \
        postgres:16 >/dev/null
    POSTGRES_PORT="$E2E_POSTGRES_PORT"
else
    echo "Starting isolated E2E PostgreSQL on a random host port..."
    docker run --rm -d \
        --name "$CONTAINER_NAME" \
        -e POSTGRES_USER=postgres \
        -e POSTGRES_PASSWORD=postgres \
        -e POSTGRES_DB=heym_e2e \
        -p "127.0.0.1::5432" \
        postgres:16 >/dev/null
    POSTGRES_PORT="$(docker port "$CONTAINER_NAME" 5432/tcp | sed -n 's/.*:\([0-9][0-9]*\)$/\1/p' | head -1)"
fi

if [ -z "$POSTGRES_PORT" ]; then
    echo "Unable to determine the E2E PostgreSQL host port"
    exit 1
fi

DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:${POSTGRES_PORT}/heym_e2e"
echo "E2E run ${RUN_ID}: postgres=${POSTGRES_PORT}, backend=${BACKEND_PORT}, frontend=${FRONTEND_PORT}"
echo "Artifacts: frontend/${ARTIFACT_DIR}"

attempt=0
until docker exec "$CONTAINER_NAME" pg_isready -U postgres -d heym_e2e >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ]; then
        echo "E2E PostgreSQL did not become ready"
        exit 1
    fi
    sleep 1
done

# Install pgvector into the stock postgres:16 image so the migration's
# CREATE EXTENSION works (opt-in Postgres RAG backend). Non-fatal.
docker exec -u root "$CONTAINER_NAME" sh -c \
    "apt-get update -qq && apt-get install -y -qq --no-install-recommends postgresql-16-pgvector" \
    >/dev/null 2>&1 || echo "pgvector install skipped for E2E (Qdrant RAG still works)"

echo "Applying E2E database migrations..."
cd "$REPO_ROOT/backend"
migration_attempt=0
until DATABASE_URL="$DATABASE_URL" \
    SECRET_KEY=e2e-test-secret-key-for-playwright-only \
    ENCRYPTION_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
    uv run alembic upgrade head; do
    migration_attempt=$((migration_attempt + 1))
    if [ "$migration_attempt" -ge 10 ]; then
        echo "E2E database migrations failed after ${migration_attempt} attempts"
        exit 1
    fi
    echo "Database port is not ready yet; retrying migrations..."
    sleep 2
done

echo "Installing the Playwright Chromium browser..."
cd "$REPO_ROOT/frontend"
bunx playwright install chromium

echo "Running frontend E2E tests..."
set +e
DATABASE_URL="$DATABASE_URL" \
E2E_FRONTEND_PORT="$FRONTEND_PORT" \
E2E_BACKEND_PORT="$BACKEND_PORT" \
E2E_ARTIFACT_DIR="$ARTIFACT_DIR" \
bun run test:e2e "$@"
TEST_STATUS=$?
set -e

mkdir -p .e2e-artifacts
ln -sfn "$(cd "$ARTIFACT_DIR" && pwd)" .e2e-artifacts/latest
echo "Playwright report: frontend/${ARTIFACT_DIR}/playwright-report"
exit "$TEST_STATUS"
