"""HTTP router for the ``/analytics`` endpoint group (Phase 9).

This module's only job is HTTP plumbing — declaring routes, validating
query parameters via FastAPI's ``Query``, instantiating the service with
the injected session, and returning the service's result directly. No SQL
and no business logic lives here, matching the convention documented in
``app/api/mock/router.py``.

Endpoints
---------
GET /analytics/total-orders
GET /analytics/total-revenue
GET /analytics/total-refunds
GET /analytics/net-revenue
GET /analytics/average-order-value
GET /analytics/repeat-customer-revenue
GET /analytics/revenue-trends
GET /analytics/top-customers

Performance
-----------
Every endpoint reads from the pre-aggregated ``daily_revenue`` /
``customer_metrics`` tables (or, for ``repeat-customer-revenue``, a narrow
``customer_id IN (...)``-filtered query that uses the existing
``ix_orders_customer_id`` index). None of these endpoints scan the
unfiltered ``orders`` or ``refunds`` tables, keeping response times well
under the 2-second SLA even at 1M+ orders.
"""

from __future__ import annotations

from datetime import date as Date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.analytics import (
    AverageOrderValueResponse,
    NetRevenueResponse,
    RepeatCustomerRevenueResponse,
    RevenueTrendPoint,
    TopCustomerEntry,
    TotalOrdersResponse,
    TotalRefundsResponse,
    TotalRevenueResponse,
)
from app.services.analytics import AnalyticsService

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
)


# ---------------------------------------------------------------------------
# Dependency: AnalyticsService
# ---------------------------------------------------------------------------


def _get_analytics_service(db: Session = Depends(get_db)) -> AnalyticsService:
    """Construct an ``AnalyticsService`` bound to the current request's session.

    Mirrors ``_get_mock_service`` in ``app/api/mock/router.py``.
    """
    return AnalyticsService(db)


# ---------------------------------------------------------------------------
# GET /analytics/total-orders
# ---------------------------------------------------------------------------


@router.get(
    "/total-orders",
    response_model=TotalOrdersResponse,
    summary="Total orders (all time)",
    description=(
        "Returns the all-time count of orders, summed from the "
        "pre-aggregated ``daily_revenue`` table rather than scanning "
        "``orders`` directly."
    ),
)
def get_total_orders(
    service: AnalyticsService = Depends(_get_analytics_service),
) -> TotalOrdersResponse:
    return service.get_total_orders()


# ---------------------------------------------------------------------------
# GET /analytics/total-revenue
# ---------------------------------------------------------------------------


@router.get(
    "/total-revenue",
    response_model=TotalRevenueResponse,
    summary="Total revenue (all time)",
    description=(
        "Returns the all-time gross revenue (sum of order amounts), "
        "summed from the pre-aggregated ``daily_revenue`` table."
    ),
)
def get_total_revenue(
    service: AnalyticsService = Depends(_get_analytics_service),
) -> TotalRevenueResponse:
    return service.get_total_revenue()


# ---------------------------------------------------------------------------
# GET /analytics/total-refunds
# ---------------------------------------------------------------------------


@router.get(
    "/total-refunds",
    response_model=TotalRefundsResponse,
    summary="Total refunds (all time)",
    description=(
        "Returns the all-time refund total, summed from the "
        "pre-aggregated ``daily_revenue`` table."
    ),
)
def get_total_refunds(
    service: AnalyticsService = Depends(_get_analytics_service),
) -> TotalRefundsResponse:
    return service.get_total_refunds()


# ---------------------------------------------------------------------------
# GET /analytics/net-revenue
# ---------------------------------------------------------------------------


@router.get(
    "/net-revenue",
    response_model=NetRevenueResponse,
    summary="Net revenue (all time)",
    description=(
        "Returns all-time revenue minus refunds, summed from the "
        "pre-aggregated ``daily_revenue`` table."
    ),
)
def get_net_revenue(
    service: AnalyticsService = Depends(_get_analytics_service),
) -> NetRevenueResponse:
    return service.get_net_revenue()


# ---------------------------------------------------------------------------
# GET /analytics/average-order-value
# ---------------------------------------------------------------------------


@router.get(
    "/average-order-value",
    response_model=AverageOrderValueResponse,
    summary="Average order value (all time)",
    description=(
        "Returns all-time gross revenue divided by all-time order count. "
        "Returns ``0`` if there are no orders yet."
    ),
)
def get_average_order_value(
    service: AnalyticsService = Depends(_get_analytics_service),
) -> AverageOrderValueResponse:
    return service.get_average_order_value()


# ---------------------------------------------------------------------------
# GET /analytics/repeat-customer-revenue
# ---------------------------------------------------------------------------


@router.get(
    "/repeat-customer-revenue",
    response_model=RepeatCustomerRevenueResponse,
    summary="Revenue from repeat customers",
    description=(
        "Returns net revenue (orders minus refunds) generated by customers "
        "with more than one order. Repeat-customer status is resolved from "
        "``customer_metrics.order_count``; the revenue figure is computed "
        "from ``orders``/``refunds`` filtered to that customer set, since "
        "``customer_metrics`` does not currently store a refund-adjusted "
        "figure (see ``AnalyticsRepository`` docstring)."
    ),
)
def get_repeat_customer_revenue(
    service: AnalyticsService = Depends(_get_analytics_service),
) -> RepeatCustomerRevenueResponse:
    return service.get_repeat_customer_revenue()


# ---------------------------------------------------------------------------
# GET /analytics/revenue-trends
# ---------------------------------------------------------------------------


@router.get(
    "/revenue-trends",
    response_model=list[RevenueTrendPoint],
    summary="Daily revenue trend",
    description=(
        "Returns net revenue per calendar day from the pre-aggregated "
        "``daily_revenue`` table, ordered by date ascending. Optionally "
        "restrict the range with ``start_date``/``end_date`` "
        "(``YYYY-MM-DD``, inclusive)."
    ),
)
def get_revenue_trends(
    start_date: Annotated[
        Date | None,
        Query(description="Inclusive start of the date range (YYYY-MM-DD)."),
    ] = None,
    end_date: Annotated[
        Date | None,
        Query(description="Inclusive end of the date range (YYYY-MM-DD)."),
    ] = None,
    service: AnalyticsService = Depends(_get_analytics_service),
) -> list[RevenueTrendPoint]:
    return service.get_revenue_trends(start_date=start_date, end_date=end_date)


# ---------------------------------------------------------------------------
# GET /analytics/top-customers
# ---------------------------------------------------------------------------


@router.get(
    "/top-customers",
    response_model=list[TopCustomerEntry],
    summary="Top customers by lifetime spend",
    description=(
        "Returns the top ``limit`` customers ordered by lifetime spend "
        "descending, read directly from the pre-aggregated "
        "``customer_metrics`` table via "
        "``ix_customer_metrics_total_spend_desc`` (index scan, no sort step)."
    ),
)
def get_top_customers(
    limit: Annotated[
        int,
        Query(ge=1, le=1000, description="Maximum number of customers to return (max 1000)."),
    ] = 10,
    service: AnalyticsService = Depends(_get_analytics_service),
) -> list[TopCustomerEntry]:
    return service.get_top_customers(limit=limit)
