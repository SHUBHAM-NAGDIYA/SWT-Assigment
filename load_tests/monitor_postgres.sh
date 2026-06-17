#!/usr/bin/env bash
# =============================================================================
# PostgreSQL Monitor — run this in a SEPARATE terminal during load tests
# Polls key metrics every 5 seconds and appends to a log file
# Usage: bash monitor_postgres.sh [db_name] [pg_user]
# =============================================================================

DB="${1:-analytics_db}"
PG_USER="${2:-postgres}"
INTERVAL=5
LOG_FILE="./results/postgres_monitor.log"

mkdir -p ./results

echo "PostgreSQL Monitor started — DB=$DB  interval=${INTERVAL}s"
echo "Output: $LOG_FILE"
echo "Press Ctrl+C to stop."
echo ""

while true; do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

    psql -U "$PG_USER" -d "$DB" -t -A -F',' << SQL >> "$LOG_FILE" 2>&1
SELECT
    '$TIMESTAMP'                                          AS ts,

    -- Active connections
    (SELECT count(*) FROM pg_stat_activity
     WHERE state = 'active')                             AS active_conns,

    -- Idle connections
    (SELECT count(*) FROM pg_stat_activity
     WHERE state = 'idle')                               AS idle_conns,

    -- Waiting connections (lock waits)
    (SELECT count(*) FROM pg_stat_activity
     WHERE wait_event_type IS NOT NULL)                  AS waiting_conns,

    -- Cache hit ratio (target > 99%)
    (SELECT round(
        sum(heap_blks_hit)::numeric /
        nullif(sum(heap_blks_hit) + sum(heap_blks_read), 0) * 100, 2
    ) FROM pg_statio_user_tables)                        AS cache_hit_pct,

    -- Transactions per second (approximate)
    (SELECT xact_commit + xact_rollback
     FROM pg_stat_database
     WHERE datname = '$DB')                              AS total_txns,

    -- Deadlocks
    (SELECT deadlocks
     FROM pg_stat_database
     WHERE datname = '$DB')                              AS deadlocks,

    -- Temp files written (indicates sort/hash spills — add work_mem)
    (SELECT temp_files
     FROM pg_stat_database
     WHERE datname = '$DB')                              AS temp_files,

    -- Longest running query duration (ms)
    (SELECT round(max(extract(epoch FROM (now() - query_start)) * 1000))
     FROM pg_stat_activity
     WHERE state = 'active'
       AND query_start IS NOT NULL)                      AS max_query_ms;
SQL

    # Also show currently running slow queries (> 500ms) to stdout
    SLOW=$(psql -U "$PG_USER" -d "$DB" -t -A 2>/dev/null << SQL
SELECT pid,
       round(extract(epoch FROM (now() - query_start)) * 1000) AS ms,
       left(query, 80) AS query_snippet
FROM pg_stat_activity
WHERE state = 'active'
  AND query_start IS NOT NULL
  AND extract(epoch FROM (now() - query_start)) > 0.5
ORDER BY ms DESC
LIMIT 5;
SQL
    )

    if [ -n "$SLOW" ]; then
        echo "[$TIMESTAMP] SLOW QUERIES (>500ms):"
        echo "$SLOW"
        echo "---"
    fi

    sleep "$INTERVAL"
done
