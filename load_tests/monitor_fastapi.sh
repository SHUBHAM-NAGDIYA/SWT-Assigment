#!/usr/bin/env bash
# =============================================================================
# FastAPI Process Monitor — run in a SEPARATE terminal during load tests
# Tracks CPU, memory, open file descriptors, and thread count
# Usage: bash monitor_fastapi.sh [uvicorn_port]
# =============================================================================

PORT="${1:-8000}"
INTERVAL=5
LOG_FILE="./results/fastapi_monitor.log"

mkdir -p ./results

# Find the uvicorn PID listening on the given port
get_pid() {
    # Works on Linux; on macOS replace with: lsof -ti tcp:$PORT | head -1
    ss -tlnp 2>/dev/null | grep ":${PORT} " | grep -oP 'pid=\K[0-9]+' | head -1 \
    || lsof -ti "tcp:${PORT}" 2>/dev/null | head -1
}

PID=$(get_pid)
if [ -z "$PID" ]; then
    echo "ERROR: No process found on port $PORT. Is uvicorn running?"
    exit 1
fi

echo "FastAPI Monitor — PID=$PID  port=$PORT  interval=${INTERVAL}s"
echo "Output: $LOG_FILE"
echo "Columns: timestamp, cpu_pct, rss_mb, vms_mb, open_fds, threads"
echo "Press Ctrl+C to stop."
echo ""

# Write CSV header
echo "timestamp,cpu_pct,rss_mb,vms_mb,open_fds,threads" >> "$LOG_FILE"

while kill -0 "$PID" 2>/dev/null; do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

    # Use /proc on Linux for zero-dependency monitoring
    if [ -f "/proc/$PID/status" ]; then
        RSS_KB=$(grep VmRSS "/proc/$PID/status" 2>/dev/null | awk '{print $2}')
        VMS_KB=$(grep VmSize "/proc/$PID/status" 2>/dev/null | awk '{print $2}')
        THREADS=$(grep Threads "/proc/$PID/status" 2>/dev/null | awk '{print $2}')
        RSS_MB=$(( ${RSS_KB:-0} / 1024 ))
        VMS_MB=$(( ${VMS_KB:-0} / 1024 ))
        FDS=$(ls /proc/$PID/fd 2>/dev/null | wc -l)
    else
        # macOS fallback
        RSS_MB=$(ps -o rss= -p "$PID" 2>/dev/null | awk '{printf "%.0f", $1/1024}')
        VMS_MB=$(ps -o vsz= -p "$PID" 2>/dev/null | awk '{printf "%.0f", $1/1024}')
        THREADS=$(ps -o nlwp= -p "$PID" 2>/dev/null | tr -d ' ')
        FDS=$(lsof -p "$PID" 2>/dev/null | wc -l)
    fi

    # CPU% via ps (averaged over last interval)
    CPU=$(ps -p "$PID" -o %cpu= 2>/dev/null | tr -d ' ' || echo "0")

    ROW="$TIMESTAMP,$CPU,${RSS_MB:-0},${VMS_MB:-0},${FDS:-0},${THREADS:-0}"
    echo "$ROW" >> "$LOG_FILE"
    echo "$ROW"

    # Alert thresholds
    if [ "${RSS_MB:-0}" -gt 1024 ]; then
        echo "  ⚠  HIGH MEMORY: ${RSS_MB}MB RSS — check for memory leak"
    fi
    if (( $(echo "$CPU > 90" | bc -l 2>/dev/null || echo 0) )); then
        echo "  ⚠  HIGH CPU: ${CPU}% — may indicate missing DB indexes"
    fi

    sleep "$INTERVAL"
done

echo "FastAPI process $PID has exited — monitor stopping."
