#!/bin/sh
# run_tests.sh - Run all backend unit tests in parallel and report results.
#
# Usage: sh run_tests.sh [pytest-extra-args...]
#        ./run_tests.sh [pytest-extra-args...]

set -u

START_TS=$(date +%s)

BACKEND_DIR="$(cd "$(dirname "$0")/backend" && pwd)"
TEST_DIR="$BACKEND_DIR/tests"

# Count test files first
SUITE_COUNT=0
for f in "$TEST_DIR"/test_*.py; do
    [ -f "$f" ] && SUITE_COUNT=$((SUITE_COUNT + 1))
done

if [ "$SUITE_COUNT" -eq 0 ]; then
    echo "No test files found in $TEST_DIR"
    exit 1
fi

# Temp dir for per-suite output and exit codes; cleaned up on exit
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

echo "Running $SUITE_COUNT test suites in parallel..."
echo "----------------------------------------"

# Launch each suite as a background job
for f in "$TEST_DIR"/test_*.py; do
    [ -f "$f" ] || continue
    name="$(basename "$f")"
    out="$WORK_DIR/$name.out"
    code_file="$WORK_DIR/$name.code"
    (
        cd "$BACKEND_DIR"
        uv run pytest "$f" -v "$@" > "$out" 2>&1
        echo $? > "$code_file"
    ) &
done

# Wait for all background jobs to finish
wait

# Report results in a deterministic order
OVERALL=0
TOTAL_PASSED=0
TOTAL_FAILED=0

for f in "$TEST_DIR"/test_*.py; do
    [ -f "$f" ] || continue
    name="$(basename "$f")"
    out="$WORK_DIR/$name.out"
    code_file="$WORK_DIR/$name.code"

    code=0
    [ -f "$code_file" ] && code="$(cat "$code_file")"

    if [ "$code" -eq 0 ]; then
        marker="PASS"
    else
        marker="FAIL"
        OVERALL=1
    fi

    # Extract passed/failed counts from pytest summary line
    summary="$(grep -E "passed|failed|error" "$out" | tail -1)"
    passed="$(echo "$summary" | grep -oE "[0-9]+ passed" | grep -oE "[0-9]+")"
    failed="$(echo "$summary" | grep -oE "[0-9]+ failed" | grep -oE "[0-9]+")"
    [ -n "$passed" ] && TOTAL_PASSED=$((TOTAL_PASSED + passed))
    [ -n "$failed" ] && TOTAL_FAILED=$((TOTAL_FAILED + failed))

    echo ""
    echo "=== [$marker] $name ==="
    if [ "$code" -ne 0 ]; then
        cat "$out"
    else
        echo "$summary"
    fi
done

echo ""
echo "----------------------------------------"
TOTAL=$((TOTAL_PASSED + TOTAL_FAILED))
END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))
if [ "$OVERALL" -eq 0 ]; then
    echo "$TOTAL tests, $TOTAL_PASSED passed — All test suites passed. (wall clock: ${ELAPSED}s)"
else
    echo "$TOTAL tests, $TOTAL_PASSED passed, $TOTAL_FAILED failed — One or more test suites FAILED. (wall clock: ${ELAPSED}s)"
fi
exit "$OVERALL"
