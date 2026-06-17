"""HTTP router for the ``/aggregates`` endpoint group.

Endpoints
---------
POST /aggregates/refresh
    Triggers the aggregate refresh pipeline as a background task.
    Returns HTTP 202 immediately.  Rejects concurrent runs with HTTP 409.

GET  /aggregates/status
    Returns a snapshot of the refresh state: lifecycle status, row counts,
    timestamps, duration, and any error message.

GET  /aggregates/daily-revenue
    Paginated read of the ``daily_revenue`` pre-aggregated table.
    Ordered by date descending (most recent first) — the natural order for
    a dashboard showing "latest revenue trends".

GET  /aggregates/customer-metrics
    Paginated read of the ``customer_metrics`` pre-aggregated table.
    Ordered by ``total_spend`` descending (highest-value customers first).

Design notes
------------
Both read endpoints expose the aggregate tables directly rather than going
through the service layer, because there is no business logic to apply —
the data is already in its final form.  The repository handles the query;
the router maps it into the paginated envelope.

A ``page_size`` ceiling of 1 000 is enforced to cap response payload size.
For very large exports a streaming/CSV endpoint would be more appropriate,
but that is out of scope for this phase.
"""

from __future__ import annotations

import logging
import math
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.aggregate_state import AggregateStatus, aggregate_state
from app.core.database import SessionLocal, get_db
from app.repositories.aggregates import AggregateRepository
from app.schemas.aggregates import (
    AggregateRefreshResponse,
    AggregateStatus,
    AggregateStatusResponse,
    CustomerMetricsSchema,
    DailyRevenueSchema,
)
from app.schemas.pagination import PaginatedResponse
from app.services.aggregates import run_aggregate_refresh

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/aggregates",
    tags=["aggregates"],
)

# ---------------------------------------------------------------------------
# Reusable pagination query-parameter annotations
# ---------------------------------------------------------------------------

PageParam = Annotated[int, Query(ge=1, description="Page number (1-based).")]
PageSizeParam = Annotated[
    int, Query(ge=1, le=1000, description="Items per page (max 1 000).")
]


# ---------------------------------------------------------------------------
# POST /aggregates/refresh
# ---------------------------------------------------------------------------


@router.post(
    "/refresh",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AggregateRefreshResponse,
    summary="Trigger aggregate refresh",
    description=(
        "Recomputes ``daily_revenue`` and ``customer_metrics`` from the raw "
        "``orders`` and ``refunds`` tables.  Runs as a background task; "
        "returns HTTP 202 immediately.\n\n"
        "Returns **HTTP 409** if a refresh is already running.\n\n"
        "The refresh is **idempotent**: re-running it produces the same "
        "result as running it once.  Safe to call after every ingestion."
    ),
)
async def trigger_refresh(
    background_tasks: BackgroundTasks,
) -> AggregateRefreshResponse:
    """Launch the aggregate refresh pipeline in the background.

    Raises
    ------
    HTTPException (409)
        If a refresh is already in progress.
    """
    if aggregate_state.is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An aggregate refresh is already running. "
                "Poll GET /aggregates/status to monitor progress."
            ),
        )

    log.info("Aggregate refresh requested — scheduling background task.")
    background_tasks.add_task(run_aggregate_refresh, SessionLocal)

    return AggregateRefreshResponse(
        message="Aggregate refresh started successfully.",
        status=AggregateStatus.RUNNING,
    )


# ---------------------------------------------------------------------------
# GET /aggregates/status
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=AggregateStatusResponse,
    summary="Query refresh progress",
    description=(
        "Returns the current state of the aggregate refresh pipeline, "
        "including lifecycle status, row counts per table, wall-clock "
        "duration, and any error from the most recent run."
    ),
)
def get_refresh_status() -> AggregateStatusResponse:
    """Return a live snapshot of the aggregate refresh state.

    Synchronous — only reads from an in-memory object; no I/O required.
    FastAPI runs sync handlers in the thread-pool executor automatically.
    """
    return AggregateStatusResponse(
        status=aggregate_state.status,
        daily_revenue_rows=aggregate_state.daily_revenue_rows,
        customer_metrics_rows=aggregate_state.customer_metrics_rows,
        started_at=aggregate_state.started_at,
        finished_at=aggregate_state.finished_at,
        duration_seconds=aggregate_state.duration_seconds,
        error_detail=aggregate_state.error_detail,
    )


# ---------------------------------------------------------------------------
# GET /aggregates/daily-revenue
# ---------------------------------------------------------------------------


@router.get(
    "/daily-revenue",
    response_model=PaginatedResponse[DailyRevenueSchema],
    summary="List daily revenue (paginated)",
    description=(
        "Returns pre-aggregated daily revenue rows ordered by date descending.  "
        "Run ``POST /aggregates/refresh`` first to populate this table."
    ),
)
def list_daily_revenue(
    page: PageParam = 1,
    page_size: PageSizeParam = 30,
    db: Session = Depends(get_db),
) -> PaginatedResponse[DailyRevenueSchema]:
    """Retrieve one page of daily revenue records.

    Ordered by date descending so the most recent days appear on page 1 —
    matching the typical dashboard use-case.
    """
    from sqlalchemy import func, select
    from sqlalchemy.orm import load_only

    from app.models.daily_revenue import DailyRevenue

    total: int = db.scalar(
        select(func.count()).select_from(DailyRevenue)
    ) or 0
    rows = db.scalars(
        select(DailyRevenue)
        .options(
            load_only(
                DailyRevenue.date,
                DailyRevenue.total_orders,
                DailyRevenue.total_revenue,
                DailyRevenue.total_refunds,
                DailyRevenue.net_revenue,
            )
        )
        .order_by(DailyRevenue.date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return PaginatedResponse[DailyRevenueSchema].build(
        page=page,
        page_size=page_size,
        total=total,
        data=[DailyRevenueSchema.model_validate(r) for r in rows],
    )


# ---------------------------------------------------------------------------
# GET /aggregates/customer-metrics
# ---------------------------------------------------------------------------


@router.get(
    "/customer-metrics",
    response_model=PaginatedResponse[CustomerMetricsSchema],
    summary="List customer metrics (paginated)",
    description=(
        "Returns pre-aggregated per-customer metrics ordered by total spend "
        "descending (highest-value customers first).  "
        "Run ``POST /aggregates/refresh`` first to populate this table."
    ),
)
def list_customer_metrics(
    page: PageParam = 1,
    page_size: PageSizeParam = 100,
    db: Session = Depends(get_db),
) -> PaginatedResponse[CustomerMetricsSchema]:
    """Retrieve one page of customer metric records.

    Ordered by ``total_spend DESC`` to surface the highest-value customers.
    The ``ix_customer_metrics_total_spend_desc`` index (created in Phase 3)
    covers this sort order, so PostgreSQL uses an index scan — no sort step.
    """
    from sqlalchemy import func, select
    from sqlalchemy.orm import load_only

    from app.models.customer_metrics import CustomerMetrics

    total: int = db.scalar(
        select(func.count()).select_from(CustomerMetrics)
    ) or 0
    rows = db.scalars(
        select(CustomerMetrics)
        .options(
            load_only(
                CustomerMetrics.customer_id,
                CustomerMetrics.order_count,
                CustomerMetrics.total_spend,
            )
        )
        .order_by(CustomerMetrics.total_spend.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return PaginatedResponse[CustomerMetricsSchema].build(
        page=page,
        page_size=page_size,
        total=total,
        data=[CustomerMetricsSchema.model_validate(r) for r in rows],
    )
