"""FastAPI application factory and entry point.

All routers are registered here under their canonical URL prefixes.
Import the ``app`` object from this module to run with Uvicorn::

    uvicorn app.main:app --reload

Phases implemented
------------------
- Phase 6 — Mock paginated list endpoints  (GET  /mock/*)
- Phase 7 — Ingestion pipeline             (POST /ingestion/start,
                                            GET  /ingestion/status)
- Phase 8 — Aggregate processing           (POST /aggregates/refresh,
                                            GET  /aggregates/status,
                                            GET  /aggregates/daily-revenue,
                                            GET  /aggregates/customer-metrics)
- Phase 9 — Analytics API                  (GET  /analytics/total-orders,
                                            GET  /analytics/total-revenue,
                                            GET  /analytics/total-refunds,
                                            GET  /analytics/net-revenue,
                                            GET  /analytics/average-order-value,
                                            GET  /analytics/repeat-customer-revenue,
                                            GET  /analytics/revenue-trends,
                                            GET  /analytics/top-customers)
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.aggregates.router import router as aggregates_router
from app.api.analytics.router import router as analytics_router
from app.api.ingestion.router import router as ingestion_router
from app.api.mock.router import router as mock_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Analytics API",
    version="0.3.0",
    description=(
        "Production-quality FastAPI analytics backend.\n\n"
        "Phases implemented:\n"
        "- **Phase 6** — Mock paginated list endpoints\n"
        "- **Phase 7** — Async ingestion pipeline with idempotent bulk inserts\n"
        "- **Phase 8** — Aggregate processing (daily_revenue, customer_metrics)\n"
        "- **Phase 9** — Analytics API (totals, trends, top customers)"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# Router registration
# ---------------------------------------------------------------------------

# GET  /mock/customers
# GET  /mock/orders
# GET  /mock/refunds
app.include_router(mock_router)

# POST /ingestion/start
# GET  /ingestion/status
app.include_router(ingestion_router)

# POST /aggregates/refresh
# GET  /aggregates/status
# GET  /aggregates/daily-revenue
# GET  /aggregates/customer-metrics
app.include_router(aggregates_router)

# GET  /analytics/total-orders
# GET  /analytics/total-revenue
# GET  /analytics/total-refunds
# GET  /analytics/net-revenue
# GET  /analytics/average-order-value
# GET  /analytics/repeat-customer-revenue
# GET  /analytics/revenue-trends
# GET  /analytics/top-customers
app.include_router(analytics_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"], summary="Liveness probe")
def health() -> dict[str, str]:
    """Return a simple alive signal.

    Used by load-balancers and container orchestrators to verify the process
    is running.  Does **not** check the database connection.
    """
    return {"status": "ok"}
