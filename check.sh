#!/bin/sh

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
MAX_FILE_LINES=10000

check_file_line_limits() {
    echo "Checking frontend/backend file line limits..."
    oversized_files="$(mktemp)"

    cd "$REPO_ROOT"
    git grep -I -z -l -e '' -- frontend backend \
        | xargs -0 wc -l \
        | awk -v limit="$MAX_FILE_LINES" '
            {
                count = $1
                $1 = ""
                sub(/^ +/, "")
                if ($0 != "total" && count > limit) {
                    printf "  %s %s\n", count, $0
                }
            }
        ' > "$oversized_files"

    if [ -s "$oversized_files" ]; then
        echo "Error: files must not exceed ${MAX_FILE_LINES} lines:"
        cat "$oversized_files"
        rm -f "$oversized_files"
        exit 1
    fi

    rm -f "$oversized_files"
}

check_file_line_limits

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
