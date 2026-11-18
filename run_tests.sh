#!/bin/sh
# run_tests.sh - Run all backend unit tests in parallel and report results.
#
# Usage: sh run_tests.sh [pytest-extra-args...]
#        ./run_tests.sh [pytest-extra-args...]

set -u

START_TS=$(date +%s)

BACKEND_DIR="$(cd "$(dirname "$0")/backend" && pwd)"
TEST_DIR="$BACKEND_DIR/tests"

# Measured peak per suite (~100MB average), rounded up for the heavy ones.
SUITE_MEMORY_MB=256
# Suites mix CPU and I/O, so mild oversubscription of the cores still pays off.
JOBS_PER_CPU=2
MAX_JOBS=32
# Used inside a container whose limits cannot be read: /proc/meminfo reports the host's
# memory there, and sizing against that is what gets the coding-agent runner OOM-killed.
FALLBACK_CONTAINER_MEMORY_MB=2048

# Count test files first
SUITE_COUNT=0
for f in "$TEST_DIR"/test_*.py; do
    [ -f "$f" ] && SUITE_COUNT=$((SUITE_COUNT + 1))
done

if [ "$SUITE_COUNT" -eq 0 ]; then
    echo "No test files found in $TEST_DIR"
    exit 1
fi

detect_cpus() {
    if [ -r /sys/fs/cgroup/cpu.max ]; then
        read -r quota period < /sys/fs/cgroup/cpu.max 2>/dev/null || quota=""
        if [ -n "${quota:-}" ] && [ "$quota" != "max" ] && [ "${period:-0}" -gt 0 ] 2>/dev/null; then
            echo $(((quota + period - 1) / period))
            return
        fi
    fi
    if [ -r /sys/fs/cgroup/cpu/cpu.cfs_quota_us ] && [ -r /sys/fs/cgroup/cpu/cpu.cfs_period_us ]; then
        quota=$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || echo 0)
        period=$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us 2>/dev/null || echo 0)
        if [ "$quota" -gt 0 ] 2>/dev/null && [ "$period" -gt 0 ] 2>/dev/null; then
            echo $(((quota + period - 1) / period))
            return
        fi
    fi
    if command -v nproc >/dev/null 2>&1; then
        nproc
        return
    fi
    sysctl -n hw.ncpu 2>/dev/null || echo 2
}

detect_memory_mb() {
    for limit_file in /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory/memory.limit_in_bytes; do
        [ -r "$limit_file" ] || continue
        raw=$(cat "$limit_file" 2>/dev/null || echo "")
        case "${raw:-}" in
            '' | *[!0-9]*) continue ;;
        esac
        # cgroup v1 stores a huge sentinel rather than a real limit when unrestricted.
        [ "$raw" -ge 4611686018427387904 ] 2>/dev/null && continue
        echo $((raw / 1048576))
        return
    done
    if [ ! -f /.dockerenv ]; then
        if [ -r /proc/meminfo ]; then
            kb=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo "")
            case "${kb:-}" in
                '' | *[!0-9]*) ;;
                *)
                    echo $((kb / 1024))
                    return
                    ;;
            esac
        fi
        bytes=$(sysctl -n hw.memsize 2>/dev/null || echo "")
        case "${bytes:-}" in
            '' | *[!0-9]*) ;;
            *)
                echo $((bytes / 1048576))
                return
                ;;
        esac
    fi
    echo "$FALLBACK_CONTAINER_MEMORY_MB"
}

CPUS=$(detect_cpus)
MEMORY_MB=$(detect_memory_mb)
# Two thirds of the budget: uv, the reporting shell and the page cache need the rest.
MEM_JOBS=$((MEMORY_MB * 2 / 3 / SUITE_MEMORY_MB))
JOBS=$((CPUS * JOBS_PER_CPU))
[ "$MEM_JOBS" -lt "$JOBS" ] && JOBS=$MEM_JOBS
[ "$JOBS" -gt "$MAX_JOBS" ] && JOBS=$MAX_JOBS
[ "$JOBS" -lt 1 ] && JOBS=1

# Temp dir for per-suite output and exit codes; cleaned up on exit
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

echo "Running $SUITE_COUNT test suites, $JOBS at a time (${CPUS} cpu, ${MEMORY_MB}MB available)..."
echo "----------------------------------------"

# One process per suite at once needs ~21GB and 300+ processes, which the OOM killer ends
# in any memory-limited sandbox. xargs keeps a fixed pool busy instead.
export BACKEND_DIR WORK_DIR
PYTEST_EXTRA_ARGS="$*"
export PYTEST_EXTRA_ARGS

xargs_rc=0
printf '%s\n' "$TEST_DIR"/test_*.py | xargs -P "$JOBS" -n 1 sh -c '
    suite=$1
    name=$(basename "$suite")
    cd "$BACKEND_DIR" || exit 1
    # Unquoted on purpose: extra pytest flags must word-split.
    uv run pytest "$suite" -v $PYTEST_EXTRA_ARGS > "$WORK_DIR/$name.out" 2>&1
    echo $? > "$WORK_DIR/$name.code"
' sh || xargs_rc=$?

# Report results in a deterministic order
OVERALL=0
TOTAL_PASSED=0
TOTAL_FAILED=0

for f in "$TEST_DIR"/test_*.py; do
    [ -f "$f" ] || continue
    name="$(basename "$f")"
    out="$WORK_DIR/$name.out"
    code_file="$WORK_DIR/$name.code"

    # Fail closed: a worker that died before writing a numeric status is a failure.
    code=""
    [ -f "$code_file" ] && code="$(cat "$code_file")"
    missing_status=0
    case "$code" in
        '' | *[!0-9]*)
            missing_status=1
            code=1
            ;;
    esac

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
    if [ "$missing_status" -eq 1 ]; then
        echo "Worker produced no exit status (it exited early or was killed)."
        [ -f "$out" ] && cat "$out"
    elif [ "$code" -ne 0 ]; then
        cat "$out"
    else
        echo "$summary"
    fi
done

echo ""
echo "----------------------------------------"
if [ "$xargs_rc" -ne 0 ]; then
    echo "xargs exited with status $xargs_rc"
    OVERALL=1
fi
TOTAL=$((TOTAL_PASSED + TOTAL_FAILED))
END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))
if [ "$OVERALL" -eq 0 ]; then
    echo "$TOTAL tests, $TOTAL_PASSED passed — All test suites passed. (wall clock: ${ELAPSED}s)"
else
    echo "$TOTAL tests, $TOTAL_PASSED passed, $TOTAL_FAILED failed — One or more test suites FAILED. (wall clock: ${ELAPSED}s)"
fi
exit "$OVERALL"
