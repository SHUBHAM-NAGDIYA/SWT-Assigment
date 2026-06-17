"""Aggregate refresh service.

Responsibilities
----------------
* Orchestrate the two-phase refresh: daily_revenue → customer_metrics.
* Own transaction boundaries: each phase runs in its own transaction so a
  failure in phase 2 does not roll back the already-committed phase 1.
* Update the ``AggregateState`` singleton after each phase and on completion
  or failure.
* Remain ignorant of HTTP concerns (no FastAPI imports, no response models).

Transaction design
------------------
The two aggregate tables are refreshed in **separate transactions** rather
than a single mega-transaction.  Rationale:

* ``daily_revenue`` and ``customer_metrics`` are independent tables —
  neither is a foreign-key dependency of the other.
* A single transaction wrapping both upserts would hold an ``ExclusiveLock``
  on both tables for the entire duration (potentially 30–120 s on 1M+ rows).
  Splitting into two transactions halves the lock-hold time per table.
* If phase 2 fails, phase 1 remains committed and the operator can retry
  just the failing phase.  With a single transaction both phases would
  be rolled back together, wasting the work already done.

Ordering rationale
------------------
``daily_revenue`` is refreshed before ``customer_metrics`` because:

  1. Both are purely additive aggregates of ``orders`` and ``refunds`` —
     neither depends on the other.
  2. Daily revenue is typically the first metric checked after ingestion,
     so refreshing it first makes it available sooner.

If a dependency arises in the future (e.g. ``customer_metrics`` needs a
column from ``daily_revenue``), the transaction design already supports it:
just change the ordering here.

asyncio.to_thread
-----------------
The service is called from an async context (FastAPI background task) but
SQLAlchemy is synchronous.  ``asyncio.to_thread`` offloads each blocking
database call to the OS thread-pool executor, keeping the event loop free.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.aggregate_state import AggregateState, aggregate_state
from app.repositories.aggregates import AggregateRepository

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal: per-phase refresh helpers
# ---------------------------------------------------------------------------


def _refresh_daily_revenue_sync(session: Session) -> int:
    """Execute the daily_revenue upsert inside a committed transaction.

    Uses ``session.begin()`` as a context manager: commits on success,
    rolls back automatically if an exception escapes the block.

    Parameters
    ----------
    session:
        A live SQLAlchemy ``Session``.  The session must not already be
        inside a transaction (autocommit=False sessions start one lazily
        on first statement, but ``session.begin()`` makes it explicit).

    Returns
    -------
    int
        Rows present in ``daily_revenue`` after the upsert.
    """
    repo = AggregateRepository(session)
    with session.begin():
        row_count = repo.refresh_daily_revenue()
    return row_count


def _refresh_customer_metrics_sync(session: Session) -> int:
    """Execute the customer_metrics upsert inside a committed transaction.

    Parameters
    ----------
    session:
        A live SQLAlchemy ``Session``.

    Returns
    -------
    int
        Rows present in ``customer_metrics`` after the upsert.
    """
    repo = AggregateRepository(session)
    with session.begin():
        row_count = repo.refresh_customer_metrics()
    return row_count


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_aggregate_refresh(session_factory: Any) -> None:
    """Execute the full aggregate refresh pipeline asynchronously.

    Called as a FastAPI ``BackgroundTask`` so the HTTP response is returned
    immediately and the caller polls ``GET /aggregates/status``.

    Pipeline
    --------
    Phase 1 — daily_revenue
        Single ``INSERT … SELECT … ON CONFLICT DO UPDATE`` aggregating all
        orders and refunds by calendar date.  Committed in its own
        transaction.

    Phase 2 — customer_metrics
        Single ``INSERT … SELECT … ON CONFLICT DO UPDATE`` aggregating all
        orders by customer.  Committed in its own transaction.

    Parameters
    ----------
    session_factory:
        The ``SessionLocal`` callable.  Injected (not imported) so the
        function is testable without a real database.
    """
    state: AggregateState = aggregate_state
    await state.mark_started()
    log.info("Aggregate refresh pipeline started.")

    session: Session = await asyncio.to_thread(session_factory)

    try:
        # ------------------------------------------------------------------ #
        # Phase 1 — daily_revenue                                             #
        # ------------------------------------------------------------------ #
        log.info("Phase 1/2 — refreshing daily_revenue …")
        dr_rows: int = await asyncio.to_thread(
            _refresh_daily_revenue_sync, session
        )
        await state.set_daily_revenue_rows(dr_rows)
        log.info("Phase 1/2 complete: %d rows in daily_revenue.", dr_rows)

        # ------------------------------------------------------------------ #
        # Phase 2 — customer_metrics                                          #
        # ------------------------------------------------------------------ #
        log.info("Phase 2/2 — refreshing customer_metrics …")
        cm_rows: int = await asyncio.to_thread(
            _refresh_customer_metrics_sync, session
        )
        await state.set_customer_metrics_rows(cm_rows)
        log.info("Phase 2/2 complete: %d rows in customer_metrics.", cm_rows)

        await state.mark_completed()
        log.info(
            "Aggregate refresh pipeline completed — "
            "daily_revenue=%d rows, customer_metrics=%d rows.",
            dr_rows,
            cm_rows,
        )

    except SQLAlchemyError as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        log.exception("Aggregate refresh failed with a database error: %s", error_msg)
        await state.mark_error(error_msg)
        raise

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        log.exception("Aggregate refresh failed unexpectedly: %s", error_msg)
        await state.mark_error(error_msg)
        raise

    finally:
        # Always close the session whether we succeeded or failed.
        await asyncio.to_thread(session.close)
        log.debug("Aggregate refresh DB session closed.")
