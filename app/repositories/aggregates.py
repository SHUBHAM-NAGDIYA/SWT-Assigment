"""Repository layer for aggregate table refresh.

Core SQL strategy
-----------------
Both aggregate tables are refreshed using a single
``INSERT … SELECT … ON CONFLICT … DO UPDATE SET …`` statement (PostgreSQL
"upsert").  This pattern is the industry-standard approach for maintaining
pre-aggregated summary tables and has three critical properties:

1. **Zero Python memory allocation for aggregate rows**
   The entire computation (GROUP BY, SUM, COUNT, JOIN) runs inside
   PostgreSQL.  No rows are fetched into the application process — the
   database engine writes directly from the aggregation result into the
   target table.  This remains efficient regardless of whether the source
   tables hold 1 M or 100 M rows.

2. **Idempotency**
   ``ON CONFLICT … DO UPDATE SET`` replaces any existing aggregate row for
   the same key with freshly computed values.  Re-running the refresh
   produces the same final state as running it once.  There is no need to
   ``TRUNCATE`` first (which would leave analytics endpoints returning 404s
   during the refresh window).

3. **Atomicity**
   The caller wraps each upsert in a transaction (``session.begin()`` block
   in the service layer).  If the statement fails mid-execution, PostgreSQL
   rolls the entire operation back, leaving the aggregate table in its prior
   consistent state.  Partial writes are not possible.

daily_revenue — refund attribution
-----------------------------------
Refunds are attributed to the **order's date**, not the refund's own
``created_at``.  This is the standard accounting convention: a refund
reverses the revenue recognised on the day the original order was placed.
Attributing refunds to the refund date would cause historical daily totals
to shift every time a refund is issued, which breaks dashboard trends.

The query joins ``refunds`` → ``orders`` to obtain ``orders.created_at``
for the date bucket::

    LEFT JOIN orders o ON r.order_id = o.id
    GROUP BY DATE(o.created_at AT TIME ZONE 'UTC')

``AT TIME ZONE 'UTC'``
    Seeds stored with ``timezone=True`` may carry timezone info.  Casting
    to UTC before ``DATE()`` truncation guarantees consistent date bucketing
    regardless of the application server's local timezone.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Raw SQL constants
# ---------------------------------------------------------------------------
# Stored as module-level constants (not inline strings) so they appear in
# code-search results, are easy to profile in isolation, and can be unit-
# tested by inspecting the string directly if needed.

# language=sql
_SQL_REFRESH_DAILY_REVENUE = text(
    """
    INSERT INTO daily_revenue (
        date,
        total_orders,
        total_revenue,
        total_refunds,
        net_revenue
    )
    SELECT
        DATE(o.created_at AT TIME ZONE 'UTC')          AS date,
        COUNT(o.id)                                    AS total_orders,
        COALESCE(SUM(o.amount),          0)            AS total_revenue,
        COALESCE(SUM(r.refund_per_order), 0)           AS total_refunds,
        COALESCE(SUM(o.amount), 0)
            - COALESCE(SUM(r.refund_per_order), 0)     AS net_revenue
    FROM orders o
    LEFT JOIN (
        -- Pre-aggregate refunds per order so the outer join does not
        -- multiply order rows when one order has multiple refunds.
        SELECT
            order_id,
            SUM(refund_amount) AS refund_per_order
        FROM refunds
        GROUP BY order_id
    ) r ON r.order_id = o.id
    GROUP BY DATE(o.created_at AT TIME ZONE 'UTC')
    ON CONFLICT (date) DO UPDATE SET
        total_orders  = EXCLUDED.total_orders,
        total_revenue = EXCLUDED.total_revenue,
        total_refunds = EXCLUDED.total_refunds,
        net_revenue   = EXCLUDED.net_revenue
    """
)

# language=sql
_SQL_REFRESH_CUSTOMER_METRICS = text(
    """
    INSERT INTO customer_metrics (
        customer_id,
        order_count,
        total_spend
    )
    SELECT
        customer_id,
        COUNT(id)          AS order_count,
        COALESCE(SUM(amount), 0) AS total_spend
    FROM orders
    GROUP BY customer_id
    ON CONFLICT (customer_id) DO UPDATE SET
        order_count = EXCLUDED.order_count,
        total_spend = EXCLUDED.total_spend
    """
)

# language=sql
_SQL_ROW_COUNT_DAILY_REVENUE = text(
    "SELECT COUNT(*) FROM daily_revenue"
)

# language=sql
_SQL_ROW_COUNT_CUSTOMER_METRICS = text(
    "SELECT COUNT(*) FROM customer_metrics"
)


# ---------------------------------------------------------------------------
# Repository class
# ---------------------------------------------------------------------------


class AggregateRepository:
    """Issues aggregate-refresh SQL statements against a live session.

    The caller (``AggregateService``) is responsible for transaction
    management: it calls ``session.begin()`` before creating this object
    and commits or rolls back after the method returns.  This keeps the
    repository free of transaction boilerplate and makes it easier to test
    with a pre-configured session.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ---------------------------------------------------------------------- #
    # daily_revenue                                                            #
    # ---------------------------------------------------------------------- #

    def refresh_daily_revenue(self) -> int:
        """Recompute and upsert all rows in ``daily_revenue``.

        Executes a single ``INSERT … SELECT … ON CONFLICT DO UPDATE``
        statement.  PostgreSQL aggregates every order and refund in the
        database server-side; no rows are fetched into Python.

        Returns
        -------
        int
            Number of rows now present in ``daily_revenue`` (i.e. the
            number of distinct order-dates in the source data).

        Raises
        ------
        sqlalchemy.exc.SQLAlchemyError
            Propagated as-is; the caller's transaction will roll back.
        """
        log.info("Refreshing daily_revenue …")
        self._session.execute(_SQL_REFRESH_DAILY_REVENUE)
        row_count: int = self._session.scalar(_SQL_ROW_COUNT_DAILY_REVENUE) or 0
        log.info("daily_revenue refresh complete: %d rows.", row_count)
        return row_count

    # ---------------------------------------------------------------------- #
    # customer_metrics                                                         #
    # ---------------------------------------------------------------------- #

    def refresh_customer_metrics(self) -> int:
        """Recompute and upsert all rows in ``customer_metrics``.

        Executes a single ``INSERT … SELECT … ON CONFLICT DO UPDATE``
        statement grouping orders by ``customer_id``.

        Returns
        -------
        int
            Number of rows now present in ``customer_metrics`` (i.e. the
            number of distinct customers who have placed at least one order).

        Raises
        ------
        sqlalchemy.exc.SQLAlchemyError
            Propagated as-is; the caller's transaction will roll back.
        """
        log.info("Refreshing customer_metrics …")
        self._session.execute(_SQL_REFRESH_CUSTOMER_METRICS)
        row_count: int = self._session.scalar(_SQL_ROW_COUNT_CUSTOMER_METRICS) or 0
        log.info("customer_metrics refresh complete: %d rows.", row_count)
        return row_count
