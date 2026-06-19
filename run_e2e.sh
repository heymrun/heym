#!/bin/sh

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
POSTGRES_PORT="${E2E_POSTGRES_PORT:-6544}"
CONTAINER_NAME="heym-e2e-postgres-$$"
DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:${POSTGRES_PORT}/heym_e2e"

cleanup() {
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if ! docker info >/dev/null 2>&1; then
    echo "Docker daemon is not running. Start Docker Desktop and retry ./run_e2e.sh."
    exit 1
fi

echo "Starting isolated E2E PostgreSQL on port ${POSTGRES_PORT}..."
docker run --rm -d \
    --name "$CONTAINER_NAME" \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_DB=heym_e2e \
    -p "${POSTGRES_PORT}:5432" \
    postgres:16 >/dev/null

attempt=0
until docker exec "$CONTAINER_NAME" pg_isready -U postgres -d heym_e2e >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ]; then
        echo "E2E PostgreSQL did not become ready"
        exit 1
    fi
    sleep 1
done

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
DATABASE_URL="$DATABASE_URL" bun run test:e2e "$@"
