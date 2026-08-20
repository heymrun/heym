#!/bin/sh

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Shared with the CI "check" job (see .github/workflows/pr-checks.yml) so the
# line-limit guard stays identical in both places.
sh "$REPO_ROOT/scripts/check-file-line-limits.sh"

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
