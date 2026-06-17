#!/usr/bin/env bash
# =============================================================================
# Phase 11 Load Test Runner
# Runs four load levels sequentially and saves results to ./results/
# Usage: bash run_load_tests.sh [host]
# =============================================================================

set -euo pipefail

HOST="${1:-http://localhost:8000}"
RESULTS_DIR="./results"
LOCUSTFILE="./locustfile.py"
SPAWN_RATE=10       # users added per second during ramp-up
RUN_TIME="3m"       # duration per test level

mkdir -p "$RESULTS_DIR"

USER_LEVELS=(50 100 200 500)

echo "============================================================"
echo "  Phase 11 — Analytics API Load Test"
echo "  Host      : $HOST"
echo "  Run time  : $RUN_TIME per level"
echo "  Spawn rate: $SPAWN_RATE users/s"
echo "  Results   : $RESULTS_DIR/"
echo "============================================================"

# Verify server is reachable before starting
echo "→ Checking server health …"
if ! curl -sf "$HOST/health" > /dev/null; then
    echo "ERROR: Server at $HOST is not responding. Aborting."
    exit 1
fi
echo "  Server OK"
echo ""

for USERS in "${USER_LEVELS[@]}"; do
    echo "------------------------------------------------------------"
    echo "  Running: $USERS concurrent users"
    echo "------------------------------------------------------------"

    locust \
        -f "$LOCUSTFILE" \
        --headless \
        --users "$USERS" \
        --spawn-rate "$SPAWN_RATE" \
        --run-time "$RUN_TIME" \
        --host "$HOST" \
        --csv "$RESULTS_DIR/run_${USERS}u" \
        --html "$RESULTS_DIR/run_${USERS}u.html" \
        --logfile "$RESULTS_DIR/run_${USERS}u.log" \
        2>&1 | tee "$RESULTS_DIR/run_${USERS}u_stdout.txt"

    echo ""
    echo "  → Results saved to $RESULTS_DIR/run_${USERS}u.*"
    echo ""

    # Cool-down between levels: let DB connection pool drain
    if [ "$USERS" -ne 500 ]; then
        echo "  Cooling down 30s before next level …"
        sleep 30
    fi
done

echo "============================================================"
echo "  All load test levels complete."
echo "  Generating summary …"
echo "============================================================"

# Print CSV summary for each run
for USERS in "${USER_LEVELS[@]}"; do
    CSV="$RESULTS_DIR/run_${USERS}u_stats.csv"
    if [ -f "$CSV" ]; then
        echo ""
        echo "--- $USERS users ---"
        # Print header + aggregated row (last line of CSV is Total)
        head -1 "$CSV"
        grep "Aggregated" "$CSV" || tail -1 "$CSV"
    fi
done

echo ""
echo "  HTML reports: open $RESULTS_DIR/*.html in a browser"
echo "  Done."
