"""
Phase 11 — Load Testing: Analytics API
=======================================
Framework : Locust 2.x
Target    : FastAPI analytics backend (local or remote)
Dataset   : 100k customers · 1M orders · 200k refunds

Usage
-----
# Headless (CI / automated)
locust -f locustfile.py \
       --headless \
       --users 100 \
       --spawn-rate 10 \
       --run-time 3m \
       --host http://localhost:8000 \
       --csv results/run_100u \
       --html results/run_100u.html

# Interactive web UI
locust -f locustfile.py --host http://localhost:8000

Scenarios
---------
AnalyticsUser      — realistic mixed read traffic across all 8 analytics
                     endpoints, weights match expected production traffic.
HeavyReadUser      — stress-tests the two most expensive aggregation
                     endpoints (revenue-trends, top-customers) at higher
                     concurrency to expose DB query bottlenecks.
PaginatedReadUser  — simulates a dashboard user scrolling through
                     paginated results (top-customers pages 1-5).
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from typing import Any

from locust import HttpUser, between, events, task
from locust.env import Environment

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------

BASE_HOST: str = os.getenv("LOCUST_HOST", "http://localhost:8000")

# Revenue-trends date range.  Keep narrow so the query stays warm in PG cache.
TRENDS_START: str = os.getenv("TRENDS_START", "2023-01-01")
TRENDS_END: str = os.getenv("TRENDS_END", "2024-12-31")

# top-customers: request at most this many; cycle through to simulate paging.
TOP_CUSTOMERS_LIMITS: list[int] = [10, 25, 50]

# repeat-customer-revenue threshold (dollars)
MIN_ORDERS_THRESHOLDS: list[int] = [2, 3, 5]

log = logging.getLogger("locust.analytics")


# ---------------------------------------------------------------------------
# Shared request helper
# ---------------------------------------------------------------------------

def _get(user: HttpUser, path: str, name: str, **params: Any) -> None:
    """Issue a GET request and record timing under *name* in the Locust UI.

    Parameters
    ----------
    user:   The calling ``HttpUser`` instance.
    path:   URL path, e.g. ``/analytics/total-orders``.
    name:   Label shown in the Locust statistics table.  Use a stable string
            (not one that varies per request) so results aggregate cleanly.
    **params: Query-string parameters.
    """
    with user.client.get(
        path,
        params=params or None,
        name=name,
        catch_response=True,
    ) as response:
        if response.status_code == 200:
            try:
                body = response.json()
                if body is None:
                    response.failure("Empty JSON body")
            except (json.JSONDecodeError, Exception) as exc:
                response.failure(f"Invalid JSON: {exc}")
            else:
                response.success()
        elif response.status_code == 422:
            # Validation error — likely a bad param; flag immediately.
            response.failure(f"422 Unprocessable Entity: {response.text[:200]}")
        else:
            response.failure(
                f"HTTP {response.status_code}: {response.text[:200]}"
            )


# ===========================================================================
# Scenario 1 — AnalyticsUser (primary scenario, realistic mixed traffic)
# ===========================================================================

class AnalyticsUser(HttpUser):
    """Simulates a typical dashboard user hitting all analytics endpoints.

    Weight distribution rationale
    ------------------------------
    High weight (5-8): Summary KPI endpoints — hit on every dashboard load.
    Mid weight (3-4) : Trend and repeat-revenue — refreshed on tab switch.
    Low weight (1-2) : top-customers — expensive; loaded less often.

    Wait time: 1–3 s between requests (simulates human think-time on a
    dashboard; also prevents a single user from hammering one endpoint).
    """

    wait_time = between(1, 3)
    weight = 3  # 3x more AnalyticsUsers than HeavyReadUsers

    # ---------------------------------------------------------------------- #
    # Lightweight KPI endpoints — hit frequently                              #
    # ---------------------------------------------------------------------- #

    @task(8)
    def total_orders(self) -> None:
        """GET /analytics/total-orders — simple COUNT query."""
        _get(self, "/analytics/total-orders", "/analytics/total-orders")

    @task(8)
    def total_revenue(self) -> None:
        """GET /analytics/total-revenue — SUM(amount)."""
        _get(self, "/analytics/total-revenue", "/analytics/total-revenue")

    @task(7)
    def total_refunds(self) -> None:
        """GET /analytics/total-refunds — SUM(refund_amount)."""
        _get(self, "/analytics/total-refunds", "/analytics/total-refunds")

    @task(7)
    def net_revenue(self) -> None:
        """GET /analytics/net-revenue — revenue minus refunds."""
        _get(self, "/analytics/net-revenue", "/analytics/net-revenue")

    @task(6)
    def average_order_value(self) -> None:
        """GET /analytics/average-order-value — AVG(amount)."""
        _get(
            self,
            "/analytics/average-order-value",
            "/analytics/average-order-value",
        )

    # ---------------------------------------------------------------------- #
    # Mid-weight endpoints                                                     #
    # ---------------------------------------------------------------------- #

    @task(4)
    def repeat_customer_revenue(self) -> None:
        """GET /analytics/repeat-customer-revenue — customers with >N orders."""
        threshold = random.choice(MIN_ORDERS_THRESHOLDS)
        _get(
            self,
            "/analytics/repeat-customer-revenue",
            "/analytics/repeat-customer-revenue",
            min_orders=threshold,
        )

    @task(3)
    def revenue_trends(self) -> None:
        """GET /analytics/revenue-trends — daily/monthly aggregation."""
        _get(
            self,
            "/analytics/revenue-trends",
            "/analytics/revenue-trends",
            start_date=TRENDS_START,
            end_date=TRENDS_END,
        )

    # ---------------------------------------------------------------------- #
    # Heavy endpoint — low weight                                              #
    # ---------------------------------------------------------------------- #

    @task(2)
    def top_customers(self) -> None:
        """GET /analytics/top-customers — sorted customer aggregation."""
        limit = random.choice(TOP_CUSTOMERS_LIMITS)
        _get(
            self,
            "/analytics/top-customers",
            "/analytics/top-customers",  # stable name for aggregation
            limit=limit,
        )


# ===========================================================================
# Scenario 2 — HeavyReadUser (stress-tests expensive endpoints)
# ===========================================================================

class HeavyReadUser(HttpUser):
    """Hammers the two most DB-intensive endpoints back-to-back.

    Used to surface query-plan problems, missing indexes, and connection-
    pool exhaustion that only appear under sustained load on aggregation
    queries.  A shorter wait_time (0.5–1 s) produces higher RPS than
    AnalyticsUser so bottlenecks appear faster.
    """

    wait_time = between(0.5, 1.5)
    weight = 1

    @task(5)
    def revenue_trends_stress(self) -> None:
        _get(
            self,
            "/analytics/revenue-trends",
            "/analytics/revenue-trends",
            start_date=TRENDS_START,
            end_date=TRENDS_END,
        )

    @task(5)
    def top_customers_stress(self) -> None:
        limit = random.choice(TOP_CUSTOMERS_LIMITS)
        _get(
            self,
            "/analytics/top-customers",
            "/analytics/top-customers",
            limit=limit,
        )

    @task(3)
    def repeat_customer_stress(self) -> None:
        _get(
            self,
            "/analytics/repeat-customer-revenue",
            "/analytics/repeat-customer-revenue",
            min_orders=2,
        )


# ===========================================================================
# Scenario 3 — PaginatedReadUser (simulates dashboard scrolling)
# ===========================================================================

class PaginatedReadUser(HttpUser):
    """Simulates a user paging through top-customers results.

    Real dashboards often fetch the first N rows, then load more on scroll.
    This scenario exercises the OFFSET pagination path under concurrency and
    reveals if large offsets cause performance degradation.
    """

    wait_time = between(2, 5)
    weight = 1

    def on_start(self) -> None:
        """Each user starts from page 1."""
        self._page = 1

    @task
    def paginate_top_customers(self) -> None:
        _get(
            self,
            "/analytics/top-customers",
            "/analytics/top-customers [paginated]",
            limit=25,
            offset=(self._page - 1) * 25,
        )
        self._page = (self._page % 5) + 1  # cycle pages 1–5


# ===========================================================================
# Event hooks — custom metrics printed to stdout / CSV
# ===========================================================================

@events.test_start.add_listener
def on_test_start(environment: Environment, **kwargs: Any) -> None:
    log.info("=" * 60)
    log.info("  Analytics Load Test — START")
    log.info("  Host    : %s", environment.host)
    log.info("  Workers : %d user classes", len(environment.user_classes))
    log.info("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment: Environment, **kwargs: Any) -> None:
    stats = environment.runner.stats
    log.info("=" * 60)
    log.info("  Analytics Load Test — COMPLETE")
    log.info("  Total requests  : %d", stats.total.num_requests)
    log.info("  Total failures  : %d", stats.total.num_failures)
    log.info(
        "  Failure rate    : %.2f%%",
        (stats.total.num_failures / max(stats.total.num_requests, 1)) * 100,
    )
    log.info("  Avg response    : %.0f ms", stats.total.avg_response_time)
    log.info(
        "  P95 response    : %.0f ms",
        stats.total.get_response_time_percentile(0.95),
    )
    log.info("  RPS             : %.1f", stats.total.current_rps)
    log.info("=" * 60)
