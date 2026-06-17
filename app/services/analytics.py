"""Service layer for the analytics endpoints (Phase 9).

Responsibilities
----------------
* Orchestrate ``AnalyticsRepository`` calls.
* Apply the one piece of business logic that doesn't belong in SQL —
  average-order-value's division-by-zero guard.
* Assemble the Pydantic response schemas.
* Remain ignorant of HTTP concerns (no FastAPI imports), matching
  ``MockService`` and ``AggregateService``.
"""

from __future__ import annotations

from datetime import date as Date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.repositories.analytics import AnalyticsRepository
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


class AnalyticsService:
    """Orchestrates data retrieval for the analytics endpoint group."""

    def __init__(self, session: Session) -> None:
        self._repo = AnalyticsRepository(session)

    # ------------------------------------------------------------------ #
    # Whole-history summary metrics                                        #
    # ------------------------------------------------------------------ #
    # Each of these reuses the same underlying daily_revenue summary query.
    # A future optimisation could cache one RevenueSummaryRow per request
    # if multiple summary endpoints were ever combined into one call; today
    # each is its own HTTP request so each computes its own summary.

    def get_total_orders(self) -> TotalOrdersResponse:
        """Return the all-time order count, summed from ``daily_revenue``."""
        summary = self._repo.get_revenue_summary()
        return TotalOrdersResponse(total_orders=summary.total_orders)

    def get_total_revenue(self) -> TotalRevenueResponse:
        """Return the all-time gross revenue, summed from ``daily_revenue``."""
        summary = self._repo.get_revenue_summary()
        return TotalRevenueResponse(total_revenue=summary.total_revenue)

    def get_total_refunds(self) -> TotalRefundsResponse:
        """Return the all-time refund total, summed from ``daily_revenue``."""
        summary = self._repo.get_revenue_summary()
        return TotalRefundsResponse(total_refunds=summary.total_refunds)

    def get_net_revenue(self) -> NetRevenueResponse:
        """Return the all-time net revenue, summed from ``daily_revenue``."""
        summary = self._repo.get_revenue_summary()
        return NetRevenueResponse(net_revenue=summary.net_revenue)

    def get_average_order_value(self) -> AverageOrderValueResponse:
        """Return gross revenue divided by order count.

        Guards against division by zero (no orders ingested yet / fresh
        database) by returning ``0`` rather than raising.
        """
        summary = self._repo.get_revenue_summary()
        if summary.total_orders == 0:
            average = Decimal("0")
        else:
            average = summary.total_revenue / summary.total_orders
        return AverageOrderValueResponse(average_order_value=average)

    # ------------------------------------------------------------------ #
    # Repeat-customer revenue                                              #
    # ------------------------------------------------------------------ #

    def get_repeat_customer_revenue(self) -> RepeatCustomerRevenueResponse:
        """Return net revenue from customers with more than one order.

        Two-step query (see ``AnalyticsRepository`` docstring for why this
        cannot be served from a pure aggregate-table read with the current
        Phase 8 schema):
          1. Resolve repeat-customer ids from ``customer_metrics``.
          2. Sum net revenue (orders minus refunds) restricted to those ids.
        """
        repeat_ids = self._repo.get_repeat_customer_ids()
        net_revenue = self._repo.get_net_revenue_for_customers(repeat_ids)
        return RepeatCustomerRevenueResponse(repeat_customer_revenue=net_revenue)

    # ------------------------------------------------------------------ #
    # Revenue trends                                                       #
    # ------------------------------------------------------------------ #

    def get_revenue_trends(
        self,
        *,
        start_date: Date | None = None,
        end_date: Date | None = None,
    ) -> list[RevenueTrendPoint]:
        """Return per-day net revenue, optionally restricted to a date range."""
        rows = self._repo.list_revenue_trends(start_date=start_date, end_date=end_date)
        return [RevenueTrendPoint(date=r.date, revenue=r.revenue) for r in rows]

    # ------------------------------------------------------------------ #
    # Top customers by spend                                              #
    # ------------------------------------------------------------------ #

    def get_top_customers(self, *, limit: int) -> list[TopCustomerEntry]:
        """Return the top ``limit`` customers by lifetime spend."""
        rows = self._repo.list_top_customers(limit=limit)
        return [
            TopCustomerEntry(
                customer_id=r.customer_id,
                total_spend=r.total_spend,
                order_count=r.order_count,
            )
            for r in rows
        ]
