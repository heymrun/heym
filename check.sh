#!/bin/sh

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "Running frontend checks..."
cd "$REPO_ROOT/frontend"
rm -rf dist
bun run lint
bun run typecheck

echo "Running backend checks..."
cd "$REPO_ROOT/backend"
uv run ruff format .
uv run ruff check .

echo "Running backend tests..."
cd "$REPO_ROOT"
./run_tests.sh

if [ "${SKIP_E2E:-0}" = "1" ]; then
    echo "Skipping frontend E2E tests (SKIP_E2E=1)."
else
    echo "Running frontend E2E tests..."
    ./run_e2e.sh
fi
