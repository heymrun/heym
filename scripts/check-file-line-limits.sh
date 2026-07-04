#!/bin/sh
# Fail if any tracked frontend/backend source file exceeds the line limit.
# Shared by check.sh (local) and the CI "check" job so the guard cannot drift.
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAX_FILE_LINES="${MAX_FILE_LINES:-10000}"

echo "Checking frontend/backend file line limits (max ${MAX_FILE_LINES})..."
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
echo "OK: no tracked frontend/backend file exceeds ${MAX_FILE_LINES} lines."
