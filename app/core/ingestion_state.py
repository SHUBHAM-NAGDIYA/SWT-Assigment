"""In-process ingestion state manager.

Design rationale
----------------
The state manager is a plain Python object protected by an ``asyncio.Lock``.
It lives as a module-level singleton so every coroutine in the same worker
process reads from and writes to the same object without any inter-process
communication overhead.

Why not Redis / a database table?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
For a single-worker development assignment, in-memory state is:
  * simpler to reason about (no network round-trips, no serialisation),
  * immediately consistent (no cache invalidation required),
  * trivially reset between test runs.

If the service were deployed behind multiple Uvicorn workers (e.g.
``uvicorn --workers 4``), each worker would maintain its own copy of the
state and ``GET /ingestion/status`` could return stale data depending on
which worker handles the request.  In that case, replace this module with a
Redis-backed equivalent; the service and router layers would not need to
change because they depend only on the ``IngestionState`` interface.

States
------
``idle``      No ingestion has been triggered yet, or the previous run
              finished / errored and was reset.
``running``   An ingestion is currently in progress.  Starting a second
              ingestion while one is running is rejected with HTTP 409.
``completed`` The previous run finished without error.
``error``     The previous run raised an unhandled exception.  The
              ``error_detail`` field carries a human-readable message.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class IngestionStatus(str, Enum):
    """Lifecycle states of the ingestion pipeline."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class IngestionState:
    """Thread-safe ingestion progress tracker.

    All mutation methods acquire ``self._lock`` so they are safe to call
    from concurrent asyncio tasks running in the same event loop.

    Attributes (read-only properties)
    -----------------------------------
    status              Current ``IngestionStatus``.
    customers_processed Running count of customers written to the DB.
    orders_processed    Running count of orders written to the DB.
    refunds_processed   Running count of refunds written to the DB.
    started_at          UTC timestamp when the current/last run began.
    finished_at         UTC timestamp when the current/last run ended.
    error_detail        Error message if ``status == ERROR``, else ``None``.
    """

    def __init__(self) -> None:
        self._lock: asyncio.Lock = asyncio.Lock()
        self._status: IngestionStatus = IngestionStatus.IDLE
        self._customers_processed: int = 0
        self._orders_processed: int = 0
        self._refunds_processed: int = 0
        self._started_at: Optional[datetime] = None
        self._finished_at: Optional[datetime] = None
        self._error_detail: Optional[str] = None

    # ---------------------------------------------------------------------- #
    # Read-only snapshot (no lock needed – reading an int/str is atomic in   #
    # CPython, and callers only ever need an approximate snapshot anyway)     #
    # ---------------------------------------------------------------------- #

    @property
    def status(self) -> IngestionStatus:
        return self._status

    @property
    def customers_processed(self) -> int:
        return self._customers_processed

    @property
    def orders_processed(self) -> int:
        return self._orders_processed

    @property
    def refunds_processed(self) -> int:
        return self._refunds_processed

    @property
    def started_at(self) -> Optional[datetime]:
        return self._started_at

    @property
    def finished_at(self) -> Optional[datetime]:
        return self._finished_at

    @property
    def error_detail(self) -> Optional[str]:
        return self._error_detail

    def is_running(self) -> bool:
        """Return ``True`` if an ingestion is currently in progress."""
        return self._status == IngestionStatus.RUNNING

    # ---------------------------------------------------------------------- #
    # State transitions (all acquire the lock)                                #
    # ---------------------------------------------------------------------- #

    async def mark_started(self) -> None:
        """Transition to RUNNING and reset all counters."""
        async with self._lock:
            self._status = IngestionStatus.RUNNING
            self._customers_processed = 0
            self._orders_processed = 0
            self._refunds_processed = 0
            self._started_at = datetime.now(tz=timezone.utc)
            self._finished_at = None
            self._error_detail = None

    async def add_customers(self, count: int) -> None:
        """Increment the customers-processed counter by *count*."""
        async with self._lock:
            self._customers_processed += count

    async def add_orders(self, count: int) -> None:
        """Increment the orders-processed counter by *count*."""
        async with self._lock:
            self._orders_processed += count

    async def add_refunds(self, count: int) -> None:
        """Increment the refunds-processed counter by *count*."""
        async with self._lock:
            self._refunds_processed += count

    async def mark_completed(self) -> None:
        """Transition to COMPLETED and record the finish timestamp."""
        async with self._lock:
            self._status = IngestionStatus.COMPLETED
            self._finished_at = datetime.now(tz=timezone.utc)

    async def mark_error(self, detail: str) -> None:
        """Transition to ERROR and store a human-readable message."""
        async with self._lock:
            self._status = IngestionStatus.ERROR
            self._finished_at = datetime.now(tz=timezone.utc)
            self._error_detail = detail


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

ingestion_state = IngestionState()
"""Process-wide ingestion state singleton.

Import this object wherever the current ingestion status is needed::

    from app.core.ingestion_state import ingestion_state
"""
