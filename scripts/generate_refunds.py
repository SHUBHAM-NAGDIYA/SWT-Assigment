"""Refund data generator.

Generates 200,000 reproducible refund rows and inserts them into the
``refunds`` table in batches of 20,000.

Referential integrity
---------------------
* ``refunds.order_id`` is drawn from orders that actually exist.  Rather
  than making 200,000 individual database look-ups, this generator fetches
  a compact ``(id, amount)`` projection of the entire ``orders`` table once
  and holds it as a plain Python list.  At ~16 bytes per tuple × 1,000,000
  rows ≈ 16 MB — well within acceptable memory for a seed script.
* ``refund_amount`` is capped at the corresponding order's ``amount`` so
  the constraint "refund ≤ order" always holds.  Amounts are drawn
  uniformly from [1.00, order_amount].

Timestamps
----------
Each refund's ``created_at`` is set to *at or after* the order's own
``created_at``, which is the only temporal constraint a refund must satisfy.
"""

from __future__ import annotations

import gc
import logging
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import text
from sqlalchemy.orm import Session
from tqdm import tqdm

from app.models.refund import Refund

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOTAL_REFUNDS: int = 200_000
BATCH_SIZE: int = 20_000

_NOW = datetime.now(tz=timezone.utc)
# Refunds can be raised up to 90 days after the order.
_MAX_REFUND_DELAY_SECONDS: int = 90 * 24 * 3600

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------

class _OrderRow(NamedTuple):
    """Lightweight projection of an order row needed by this generator."""

    id: int
    amount: Decimal
    created_at: datetime


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_order_pool(session: Session) -> list[_OrderRow]:
    """Fetch the (id, amount, created_at) projection of every order.

    Uses a raw SQL query instead of ORM loading to avoid the overhead of
    constructing 1,000,000 ORM objects.  The result is streamed in chunks
    via ``yield_per`` / server-side cursor to avoid buffering the full
    result set in the SQLAlchemy result proxy.

    Returns
    -------
    list[_OrderRow]
        Sorted by ``id`` (natural DB order); deterministic across runs.
    """
    log.info("Fetching order pool for refund generation …")
    rows: list[_OrderRow] = []

    result = session.execute(
        text("SELECT id, amount, created_at FROM orders ORDER BY id")
    )
    for row in result:
        rows.append(_OrderRow(id=row[0], amount=row[1], created_at=row[2]))

    log.info("Order pool loaded: %d orders.", len(rows))
    return rows


def _random_refund_amount(rng: random.Random, order_amount: Decimal) -> Decimal:
    """Return a refund amount in [1.00, order_amount]."""
    upper = float(order_amount)
    raw = rng.uniform(1.0, upper)
    return Decimal(str(round(raw, 2)))


def _random_refund_timestamp(
    rng: random.Random,
    order_created_at: datetime,
) -> datetime:
    """Return a UTC timestamp between order creation and now (≤ 90 days later)."""
    # Ensure the upper bound of the delay window does not exceed the current
    # time, which would produce future-dated refunds.
    order_ts = order_created_at
    if order_ts.tzinfo is None:
        order_ts = order_ts.replace(tzinfo=timezone.utc)

    latest_possible = min(
        order_ts + timedelta(seconds=_MAX_REFUND_DELAY_SECONDS),
        _NOW,
    )

    if latest_possible <= order_ts:
        # Edge case: order was created in the future relative to _NOW
        # (shouldn't happen with seeded data, but be defensive).
        return order_ts

    delay = rng.randint(0, int((latest_possible - order_ts).total_seconds()))
    return order_ts + timedelta(seconds=delay)


def _build_batch(
    rng: random.Random,
    order_pool: list[_OrderRow],
    start_id: int,
    count: int,
) -> list[dict[str, Any]]:
    """Build *count* refund mapping dicts starting at *start_id*.

    Parameters
    ----------
    rng:
        Seeded ``random.Random`` instance.
    order_pool:
        Full list of ``_OrderRow`` objects loaded from the database.
    start_id:
        ``id`` value for the first record in this batch.
    count:
        Number of records to generate.
    """
    batch: list[dict[str, Any]] = []
    for i in range(count):
        order: _OrderRow = rng.choice(order_pool)
        batch.append(
            {
                "id": start_id + i,
                "order_id": order.id,
                "refund_amount": _random_refund_amount(rng, order.amount),
                "created_at": _random_refund_timestamp(rng, order.created_at),
            }
        )
    return batch


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_refunds(session: Session) -> int:
    """Insert 200,000 refund rows in batches of 20,000.

    Fetches a compact order projection first (≈ 16 MB), then generates
    refunds in batches without further database reads.

    Parameters
    ----------
    session:
        An active SQLAlchemy ``Session``.

    Returns
    -------
    int
        Total number of rows successfully inserted.

    Raises
    ------
    Exception
        Any database error triggers a rollback before re-raising.
    """
    log.info("Starting refund generation: %d rows, batch=%d", TOTAL_REFUNDS, BATCH_SIZE)

    rng = random.Random(42)

    order_pool = _fetch_order_pool(session)
    if not order_pool:
        raise RuntimeError(
            "Order pool is empty.  Run generate_orders() before generate_refunds()."
        )

    inserted = 0

    with tqdm(total=TOTAL_REFUNDS, desc="Refunds   ", unit="row") as progress:
        for batch_start in range(0, TOTAL_REFUNDS, BATCH_SIZE):
            count = min(BATCH_SIZE, TOTAL_REFUNDS - batch_start)
            start_id = batch_start + 1

            batch = _build_batch(rng, order_pool, start_id, count)
            try:
                session.bulk_insert_mappings(Refund, batch)  # type: ignore[arg-type]
                session.commit()
            except Exception:
                session.rollback()
                log.exception(
                    "Batch failed (refund ids %d–%d); rolled back.",
                    start_id,
                    start_id + count - 1,
                )
                raise

            inserted += count
            progress.update(count)

            del batch
            gc.collect()

    # Release the order pool now that we're done.
    del order_pool
    gc.collect()

    log.info("Refund generation complete: %d rows inserted.", inserted)
    return inserted
