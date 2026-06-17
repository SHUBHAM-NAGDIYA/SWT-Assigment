import time
import psycopg

CONN_STR = "host=localhost dbname=SWT user=postgres password=PostgreSQL"
INTERVAL = 5  # seconds

QUERY = """
SELECT
    (SELECT count(*) FROM pg_stat_activity WHERE state = 'active')   AS active,
    (SELECT count(*) FROM pg_stat_activity WHERE state = 'idle')     AS idle,
    (SELECT count(*) FROM pg_stat_activity
     WHERE wait_event_type = 'Lock')                                  AS waiting,
    (SELECT round(
        sum(heap_blks_hit)::numeric /
        nullif(sum(heap_blks_hit) + sum(heap_blks_read), 0) * 100, 2)
     FROM pg_statio_user_tables)                                       AS cache_hit_pct,
    (SELECT round(max(
        extract(epoch FROM (now() - query_start)) * 1000))
     FROM pg_stat_activity
     WHERE state = 'active' AND query_start IS NOT NULL)              AS max_query_ms;
"""

print(f"{'Time':<12} {'Active':>7} {'Idle':>6} {'Waiting':>8} {'Cache%':>8} {'MaxQ(ms)':>10}")
print("-" * 60)

with psycopg.connect(CONN_STR) as conn:
    conn.autocommit = True
    while True:
        with conn.cursor() as cur:
            cur.execute(QUERY)
            row = cur.fetchone()
            ts = time.strftime("%H:%M:%S")
            active, idle, waiting, cache, max_q = row
            flag = "  ⚠ SLOW" if (max_q or 0) > 2000 else ""
            print(f"{ts:<12} {active or 0:>7} {idle or 0:>6} "
                  f"{waiting or 0:>8} {cache or 0:>7}% "
                  f"{int(max_q or 0):>9}ms{flag}")
        time.sleep(INTERVAL)