"""Repository layer for the analytics endpoints (Phase 9).

Design notes
------------
Every method here reads from the pre-aggregated ``daily_revenue`` and
``customer_metrics`` tables wherever the requested metric can be derived
from them, per the Phase 9 requirement to avoid scanning the million-row
``orders`` table on every request.

``daily_revenue`` already stores, per calendar day:
    total_orders, total_revenue (gross), total_refunds, net_revenue

Summing those columns across all rows gives every whole-history metric the
assignment asks for (total orders, total revenue, total refunds, net
revenue, average order value) in a single ``SELECT SUM(...) ... `` over a
table with one row per day — not one row per order. With ~1M orders ingested
over a finite date range this is a tiny table (hundreds of rows at most),
so the aggregation cost is negligible regardless of how large ``orders``
grows.

``customer_metrics`` already stores, per customer:
    order_count, total_spend (gross)

This directly serves "top customers by spend" via the
``ix_customer_metrics_total_spend_desc`` index (no sort step needed).

Repeat-customer revenue — the one query that must touch ``orders``/``refunds``
-------------------------------------------------------------------------------
Neither aggregate table stores a *net-of-refunds* figure broken out by
"is this customer a repeat customer". ``customer_metrics.total_spend`` is
gross order revenue only (see ``AggregateRepository.refresh_customer_metrics``),
and ``daily_revenue`` is bucketed by day, not by customer. Computing repeat-
customer revenue net of refunds therefore requires joining ``orders`` to
``refunds`` and filtering to the set of customer_ids already known (via
``customer_metrics.order_count > 1``) to be repeat customers.

This is still far cheaper than a naive full scan: the repeat-customer id set
is resolved first from the small ``customer_metrics`` table, and the
``orders``/``refunds`` aggregation is restricted to exactly those
customer_ids via a join, using the existing ``ix_orders_customer_id`` index
rather than scanning all 1M orders unfiltered. If this endpoint's latency
ever threatens the 2-second SLA at larger scale, the fix is to extend the
``customer_metrics`` aggregate (Phase 8) with a ``total_refunds`` column
maintained by the same upsert job, which would make this endpoint a pure
aggregate-table read like the others. See the accompanying response notes
for the suggested column and index.
"""

from __future__ import annotations

from datetime import date as Date
from decimal import Decimal
from typing import NamedTuple, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer_metrics import CustomerMetrics
from app.models.daily_revenue import DailyRevenue
from app.models.order import Order
from app.models.refund import Refund


# ---------------------------------------------------------------------------
# Lightweight row types returned by repository methods
# ---------------------------------------------------------------------------


class RevenueSummaryRow(NamedTuple):
    """Whole-history totals aggregated from ``daily_revenue``."""

    total_orders: int
    total_revenue: Decimal
    total_refunds: Decimal
    net_revenue: Decimal


class RevenueTrendRow(NamedTuple):
    """One day's net revenue, as returned by the trends query."""

    date: Date
    revenue: Decimal


class TopCustomerRow(NamedTuple):
    """One customer's ranking entry, as returned by the top-customers query."""

    customer_id: int
    total_spend: Decimal
    order_count: int


# ---------------------------------------------------------------------------
# Repository class
# ---------------------------------------------------------------------------


class AnalyticsRepository:
    """Data-access methods for the analytics endpoints.

    Mirrors the existing repository convention (``CustomerRepository``,
    ``AggregateRepository``, etc.): a plain class bound to a single
    SQLAlchemy ``Session``, no inheritance, no HTTP or pagination concerns.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Whole-history summary — backs total-orders, total-revenue,           #
    # total-refunds, net-revenue, average-order-value                       #
    # ------------------------------------------------------------------ #

    def get_revenue_summary(self) -> RevenueSummaryRow:
        """Return whole-history totals summed across ``daily_revenue``.

        Issues a single ``SELECT SUM(...)`` over the pre-aggregated table —
        one row per calendar day, not per order — so the cost is
        independent of how many orders exist in the source ``orders``
        table.

        Returns
        -------
        RevenueSummaryRow
            All-zero / zero-Decimal fields if ``daily_revenue`` has not yet
            been populated (e.g. before the first aggregate refresh).
        """
        stmt = select(
            func.coalesce(func.sum(DailyRevenue.total_orders), 0).label("total_orders"),
            func.coalesce(func.sum(DailyRevenue.total_revenue), 0).label("total_revenue"),
            func.coalesce(func.sum(DailyRevenue.total_refunds), 0).label("total_refunds"),
            func.coalesce(func.sum(DailyRevenue.net_revenue), 0).label("net_revenue"),
        )
        row = self._session.execute(stmt).one()
        return RevenueSummaryRow(
            total_orders=int(row.total_orders),
            total_revenue=Decimal(row.total_revenue),
            total_refunds=Decimal(row.total_refunds),
            net_revenue=Decimal(row.net_revenue),
        )

    # ------------------------------------------------------------------ #
    # Repeat-customer revenue                                              #
    # ------------------------------------------------------------------ #

    def get_repeat_customer_ids(self) -> Sequence[int]:
        """Return customer ids with more than one order, per ``customer_metrics``.

        Reads only ``customer_metrics`` (one row per customer who has ever
        ordered — at most 100k rows here), not ``orders``.
        """
        stmt = select(CustomerMetrics.customer_id).where(CustomerMetrics.order_count > 1)
        return list(self._session.scalars(stmt))

    def get_net_revenue_for_customers(self, customer_ids: Sequence[int]) -> Decimal:
        """Return net revenue (orders minus refunds) for the given customer ids.

        Restricting both the ``orders`` and ``refunds`` aggregation to an
        explicit ``customer_id IN (...)`` list lets PostgreSQL use
        ``ix_orders_customer_id`` instead of scanning all 1M orders.

        Parameters
        ----------
        customer_ids:
            Customer ids to include. An empty sequence short-circuits to
            ``Decimal("0")`` without issuing a query.

        Returns
        -------
        Decimal
            ``0`` if ``customer_ids`` is empty or none of the given
            customers have any orders.
        """
        if not customer_ids:
            return Decimal("0")

        gross_stmt = select(func.coalesce(func.sum(Order.amount), 0)).where(
            Order.customer_id.in_(customer_ids)
        )
        gross = Decimal(self._session.scalar(gross_stmt) or 0)

        refunds_stmt = (
            select(func.coalesce(func.sum(Refund.refund_amount), 0))
            .select_from(Refund)
            .join(Order, Order.id == Refund.order_id)
            .where(Order.customer_id.in_(customer_ids))
        )
        refunds = Decimal(self._session.scalar(refunds_stmt) or 0)

        return gross - refunds

    # ------------------------------------------------------------------ #
    # Revenue trends                                                       #
    # ------------------------------------------------------------------ #

    def list_revenue_trends(
        self,
        *,
        start_date: Date | None = None,
        end_date: Date | None = None,
    ) -> list[RevenueTrendRow]:
        """Return per-day net revenue from ``daily_revenue``, ordered by date ascending.

        Parameters
        ----------
        start_date:
            If given, only include days on or after this date (inclusive).
        end_date:
            If given, only include days on or before this date (inclusive).

        Returns
        -------
        list[RevenueTrendRow]
            Empty list if ``daily_revenue`` has no rows in range.
        """
        stmt = select(DailyRevenue.date, DailyRevenue.net_revenue).order_by(DailyRevenue.date.asc())
        if start_date is not None:
            stmt = stmt.where(DailyRevenue.date >= start_date)
        if end_date is not None:
            stmt = stmt.where(DailyRevenue.date <= end_date)

        rows = self._session.execute(stmt).all()
        return [RevenueTrendRow(date=r.date, revenue=Decimal(r.net_revenue)) for r in rows]

    # ------------------------------------------------------------------ #
    # Top customers by spend                                              #
    # ------------------------------------------------------------------ #

    def list_top_customers(self, *, limit: int) -> list[TopCustomerRow]:
        """Return the top ``limit`` customers from ``customer_metrics`` by spend.

        Ordered by ``total_spend DESC``, matching
        ``ix_customer_metrics_total_spend_desc`` so PostgreSQL serves this
        as an index scan with no sort step.

        Parameters
        ----------
        limit:
            Maximum number of customers to return. Already validated by
            the router (``ge=1``); no upper bound is enforced here since
            ``customer_metrics`` has at most one row per customer (100k).
        """
        stmt = (
            select(
                CustomerMetrics.customer_id,
                CustomerMetrics.total_spend,
                CustomerMetrics.order_count,
            )
            .order_by(CustomerMetrics.total_spend.desc())
            .limit(limit)
        )
        rows = self._session.execute(stmt).all()
        return [
            TopCustomerRow(
                customer_id=r.customer_id,
                total_spend=Decimal(r.total_spend),
                order_count=r.order_count,
            )
            for r in rows
        ]
