"""Ingestion service — orchestrates fetching from the mock API and writing to PostgreSQL.

Architecture overview
---------------------

                ┌─────────────┐    async HTTP    ┌─────────────────┐
                │  Ingestion  │ ──────────────►  │  Mock API       │
                │  Service    │ ◄──────────────  │  /mock/...      │
                └──────┬──────┘  paginated JSON  └─────────────────┘
                       │
                       │  plain dicts (batches)
                       ▼
                ┌─────────────┐   bulk INSERT    ┌─────────────────┐
                │  Ingestion  │ ──────────────►  │  PostgreSQL     │
                │  Repository │  ON CONFLICT     │  customers /    │
                └─────────────┘  DO NOTHING      │  orders /       │
                                                 │  refunds        │
                                                 └─────────────────┘

Key design decisions
--------------------

1. **asyncio.to_thread for blocking DB calls**
   SQLAlchemy is synchronous; calling it directly from an async function
   would block the event loop and degrade API responsiveness under load.
   ``asyncio.to_thread`` offloads each ``bulk_insert_*`` call to the
   default thread-pool executor so the event loop remains free to handle
   other requests while PostgreSQL is processing the batch.

2. **Configurable page size**
   ``MOCK_PAGE_SIZE`` controls how many records are fetched per HTTP
   request.  1 000 is the maximum allowed by the mock API.  Larger pages
   mean fewer round-trips but larger in-memory batches.

3. **Ingestion order**
   Customers → Orders → Refunds.  This preserves referential integrity:
   orders reference customers (FK), refunds reference orders (FK).

4. **State updates after every batch**
   Progress counters are incremented after each successful DB batch so
   ``GET /ingestion/status`` reflects live progress during a long run.

5. **Separation of concerns**
   This service knows about the mock API URL and pagination logic.
   It does not know about HTTP request objects, response models, or
   SQLAlchemy query construction — those live in the router and repository
   respectively.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

import httpx

from app.core.ingestion_state import IngestionState, ingestion_state
from app.repositories.ingestion import IngestionRepository

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Maximum records per mock-API page (the mock API caps at 1 000).
MOCK_PAGE_SIZE: int = 1_000

# Base URL for the mock API.  In production this would come from settings.
MOCK_BASE_URL: str = "http://localhost:8000"

# httpx timeout configuration: connect=5 s, read=30 s (large pages can be slow).
_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

# Retry policy: up to 3 attempts with exponential back-off (1 s, 2 s, 4 s).
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 1.0


# ---------------------------------------------------------------------------
# Internal: paginated fetcher
# ---------------------------------------------------------------------------

async def _fetch_all_pages(
    client: httpx.AsyncClient,
    path: str,
    page_size: int = MOCK_PAGE_SIZE,
) -> AsyncIterator[list[dict[str, Any]]]:
    """Async generator that yields one page of records at a time.

    Handles pagination automatically: it keeps requesting the next page
    until ``page > total_pages`` (or the API returns an empty ``data``
    list, whichever comes first).

    Implements simple exponential-back-off retry on transient HTTP errors
    (status 5xx or network-level exceptions).

    Parameters
    ----------
    client:
        A live ``httpx.AsyncClient`` instance.
    path:
        Endpoint path relative to ``MOCK_BASE_URL``, e.g. ``/mock/customers``.
    page_size:
        Number of records to request per page.

    Yields
    ------
    list[dict[str, Any]]
        The ``data`` array from a single API page.
    """
    page = 1
    total_pages: int | None = None

    while True:
        if total_pages is not None and page > total_pages:
            break

        url = f"{MOCK_BASE_URL}{path}"
        params = {"page": page, "page_size": page_size}

        # Retry loop with exponential back-off.
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                break  # success — exit retry loop
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                if attempt == _MAX_RETRIES:
                    log.error(
                        "Giving up on %s page=%d after %d attempts: %s",
                        path, page, _MAX_RETRIES, exc,
                    )
                    raise
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                log.warning(
                    "Request to %s page=%d failed (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    path, page, attempt, _MAX_RETRIES, delay, exc,
                )
                await asyncio.sleep(delay)

        payload: dict[str, Any] = response.json()
        data: list[dict[str, Any]] = payload.get("data", [])
        total_pages = payload.get("total_pages", 1)

        log.info(
            "Fetched %s page %d/%d — %d records",
            path, page, total_pages, len(data),
        )

        if not data:
            break

        yield data
        page += 1


# ---------------------------------------------------------------------------
# Internal: per-entity ingestion helpers
# ---------------------------------------------------------------------------

async def _ingest_customers(
    client: httpx.AsyncClient,
    repo: IngestionRepository,
    state: IngestionState,
) -> int:
    """Fetch all customer pages and bulk-insert into PostgreSQL.

    Parameters
    ----------
    client:
        Shared ``httpx.AsyncClient``.
    repo:
        ``IngestionRepository`` bound to the current DB session.
    state:
        Live ``IngestionState`` instance for progress updates.

    Returns
    -------
    int
        Total customers inserted.
    """
    total = 0
    async for page_data in _fetch_all_pages(client, "/mock/customers"):
        # Map API field names → DB column names (they already match here,
        # but being explicit makes future divergence easy to handle).
        rows = [
            {
                "id": record["id"],
                "name": record["name"],
                "email": record["email"],
                "created_at": record["created_at"],
            }
            for record in page_data
        ]
        # Offload the blocking SQLAlchemy call to the thread-pool executor.
        inserted: int = await asyncio.to_thread(repo.bulk_insert_customers, rows)
        total += inserted
        await state.add_customers(inserted)

    return total


async def _ingest_orders(
    client: httpx.AsyncClient,
    repo: IngestionRepository,
    state: IngestionState,
) -> int:
    """Fetch all order pages and bulk-insert into PostgreSQL."""
    total = 0
    async for page_data in _fetch_all_pages(client, "/mock/orders"):
        rows = [
            {
                "id": record["id"],
                "customer_id": record["customer_id"],
                "amount": record["amount"],
                "created_at": record["created_at"],
            }
            for record in page_data
        ]
        inserted = await asyncio.to_thread(repo.bulk_insert_orders, rows)
        total += inserted
        await state.add_orders(inserted)

    return total


async def _ingest_refunds(
    client: httpx.AsyncClient,
    repo: IngestionRepository,
    state: IngestionState,
) -> int:
    """Fetch all refund pages and bulk-insert into PostgreSQL."""
    total = 0
    async for page_data in _fetch_all_pages(client, "/mock/refunds"):
        rows = [
            {
                "id": record["id"],
                "order_id": record["order_id"],
                "refund_amount": record["refund_amount"],
                "created_at": record["created_at"],
            }
            for record in page_data
        ]
        inserted = await asyncio.to_thread(repo.bulk_insert_refunds, rows)
        total += inserted
        await state.add_refunds(inserted)

    return total


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_ingestion(session_factory: Any) -> None:
    """Execute the full ingestion pipeline: customers → orders → refunds.

    This coroutine is launched as a background task by the router so the
    HTTP response is returned immediately and the caller can poll
    ``GET /ingestion/status`` for progress.

    Parameters
    ----------
    session_factory:
        The ``SessionLocal`` callable that produces a new SQLAlchemy
        ``Session``.  Passed in (rather than imported directly) to keep
        this function testable without a real database.
    """
    state = ingestion_state
    await state.mark_started()
    log.info("Ingestion pipeline started.")

    try:
        # A single DB session for the entire pipeline.  Each batch commits
        # individually inside the repository, so a failure after N batches
        # leaves those N batches persisted — re-running will skip them via
        # ON CONFLICT DO NOTHING.
        session = await asyncio.to_thread(session_factory)
        repo = IngestionRepository(session)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # --- Phase 1: Customers -----------------------------------------
            log.info("Phase 1/3 — ingesting customers …")
            c_total = await _ingest_customers(client, repo, state)
            log.info("Phase 1/3 complete: %d customers inserted.", c_total)

            # --- Phase 2: Orders --------------------------------------------
            log.info("Phase 2/3 — ingesting orders …")
            o_total = await _ingest_orders(client, repo, state)
            log.info("Phase 2/3 complete: %d orders inserted.", o_total)

            # --- Phase 3: Refunds -------------------------------------------
            log.info("Phase 3/3 — ingesting refunds …")
            r_total = await _ingest_refunds(client, repo, state)
            log.info("Phase 3/3 complete: %d refunds inserted.", r_total)

        await asyncio.to_thread(session.close)
        await state.mark_completed()
        log.info(
            "Ingestion pipeline completed — customers=%d, orders=%d, refunds=%d.",
            c_total, o_total, r_total,
        )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        log.exception("Ingestion pipeline failed: %s", error_msg)
        await state.mark_error(error_msg)
        raise
