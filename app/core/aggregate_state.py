"""In-process state manager for the aggregate refresh job.

Architecture rationale
----------------------
Mirrors the ``IngestionState`` pattern established in Phase 7, keeping the
codebase consistent and predictable for future engineers.

The state object is a process-wide singleton protected by ``asyncio.Lock``.
Reading individual integer/string attributes is atomic in CPython (GIL
protection), so status-check calls from the router do not need to acquire
the lock — they only need an approximate snapshot.  Mutation methods always
acquire the lock to prevent race conditions between the background task
updating counters and a concurrent trigger request reading ``is_running``.

Replacement path for multi-worker deployments
---------------------------------------------
Replace ``aggregate_state`` with a Redis-backed equivalent that stores the
same fields in a hash key.  The router and service interfaces remain
unchanged because they depend only on the ``AggregateState`` public API.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from app.schemas.aggregates import AggregateStatus


class AggregateState:
    """Thread-safe tracker for the aggregate refresh lifecycle.

    Attributes (read via properties)
    ---------------------------------
    status                  Current ``AggregateStatus``.
    daily_revenue_rows      Rows upserted into ``daily_revenue`` last run.
    customer_metrics_rows   Rows upserted into ``customer_metrics`` last run.
    started_at              UTC start timestamp of the current/last run.
    finished_at             UTC end timestamp of the current/last run.
    duration_seconds        Wall-clock duration of the last completed run.
    error_detail            Error message if status is ERROR, else None.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._status = AggregateStatus.IDLE
        self._daily_revenue_rows: int = 0
        self._customer_metrics_rows: int = 0
        self._started_at: Optional[datetime] = None
        self._finished_at: Optional[datetime] = None
        self._duration_seconds: Optional[float] = None
        self._error_detail: Optional[str] = None

    # ---------------------------------------------------------------------- #
    # Read-only properties (no lock — CPython atomic reads are sufficient)    #
    # ---------------------------------------------------------------------- #

    @property
    def status(self) -> AggregateStatus:
        return self._status

    @property
    def daily_revenue_rows(self) -> int:
        return self._daily_revenue_rows

    @property
    def customer_metrics_rows(self) -> int:
        return self._customer_metrics_rows

    @property
    def started_at(self) -> Optional[datetime]:
        return self._started_at

    @property
    def finished_at(self) -> Optional[datetime]:
        return self._finished_at

    @property
    def duration_seconds(self) -> Optional[float]:
        return self._duration_seconds

    @property
    def error_detail(self) -> Optional[str]:
        return self._error_detail

    def is_running(self) -> bool:
        """Return ``True`` if a refresh job is currently active."""
        return self._status == AggregateStatus.RUNNING

    # ---------------------------------------------------------------------- #
    # State transitions (all acquire lock for safe concurrent mutation)       #
    # ---------------------------------------------------------------------- #

    async def mark_started(self) -> None:
        """Transition to RUNNING and zero-out all counters from the prior run."""
        async with self._lock:
            self._status = AggregateStatus.RUNNING
            self._daily_revenue_rows = 0
            self._customer_metrics_rows = 0
            self._started_at = datetime.now(tz=timezone.utc)
            self._finished_at = None
            self._duration_seconds = None
            self._error_detail = None

    async def set_daily_revenue_rows(self, count: int) -> None:
        """Record how many rows were written to ``daily_revenue``."""
        async with self._lock:
            self._daily_revenue_rows = count

    async def set_customer_metrics_rows(self, count: int) -> None:
        """Record how many rows were written to ``customer_metrics``."""
        async with self._lock:
            self._customer_metrics_rows = count

    async def mark_completed(self) -> None:
        """Transition to COMPLETED and compute the wall-clock duration."""
        async with self._lock:
            self._status = AggregateStatus.COMPLETED
            self._finished_at = datetime.now(tz=timezone.utc)
            if self._started_at is not None:
                self._duration_seconds = (
                    self._finished_at - self._started_at
                ).total_seconds()

    async def mark_error(self, detail: str) -> None:
        """Transition to ERROR and store the exception summary."""
        async with self._lock:
            self._status = AggregateStatus.ERROR
            self._finished_at = datetime.now(tz=timezone.utc)
            if self._started_at is not None:
                self._duration_seconds = (
                    self._finished_at - self._started_at
                ).total_seconds()
            self._error_detail = detail


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

aggregate_state = AggregateState()
"""Process-wide aggregate-refresh state singleton.

Import wherever the current refresh status is needed::

    from app.core.aggregate_state import aggregate_state
"""
