"""Order data generator.

Generates 1,000,000 reproducible order rows and inserts them into the
``orders`` table in batches of 50,000.

Referential integrity
---------------------
``orders.customer_id`` is drawn uniformly from the range ``[1, 100_000]``
(the IDs inserted by ``generate_customers``).  No database round-trip is
needed because the customer IDs are deterministic.

Amount distribution
-------------------
Order amounts follow a log-normal distribution (mu=6, sigma=1.2) clamped
to [100.00, 50_000.00].  Log-normal is a better model for transaction
amounts than uniform because it produces a realistic right-skewed
distribution: many small orders and a long tail of large ones.

Timestamps
----------
Each order's ``created_at`` is drawn uniformly from the last two years.
Orders may pre-date or post-date the customer's own ``created_at``; a
production ingestion pipeline would enforce ordering, but for seed data the
primary goal is a wide, realistic temporal spread.
"""

from __future__ import annotations

import gc
import logging
import math
import random
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session
from tqdm import tqdm

from app.models.order import Order

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOTAL_ORDERS: int = 1_000_000
BATCH_SIZE: int = 50_000
TOTAL_CUSTOMERS: int = 100_000

AMOUNT_MIN: Decimal = Decimal("100.00")
AMOUNT_MAX: Decimal = Decimal("50000.00")

# Log-normal parameters tuned so that ~95 % of raw samples fall inside
# [AMOUNT_MIN, AMOUNT_MAX] before clamping.
_LN_MU: float = 6.0    # exp(6) ≈ 403
_LN_SIGMA: float = 1.2

_NOW = datetime.now(tz=timezone.utc)
_TWO_YEARS_AGO = _NOW - timedelta(days=730)
_WINDOW_SECONDS: int = int((_NOW - _TWO_YEARS_AGO).total_seconds())

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _random_amount(rng: random.Random) -> Decimal:
    """Return a realistic order amount in [100.00, 50_000.00]."""
    raw = math.exp(rng.gauss(_LN_MU, _LN_SIGMA))
    clamped = max(float(AMOUNT_MIN), min(float(AMOUNT_MAX), raw))
    return Decimal(str(round(clamped, 2)))


def _random_timestamp(rng: random.Random) -> datetime:
    """Return a random UTC timestamp within the last two years."""
    offset = rng.randint(0, _WINDOW_SECONDS)
    return _TWO_YEARS_AGO + timedelta(seconds=offset)


def _build_batch(
    rng: random.Random,
    start_id: int,
    count: int,
) -> list[dict[str, Any]]:
    """Build *count* order mapping dicts starting at *start_id*.

    Parameters
    ----------
    rng:
        Seeded ``random.Random`` instance.
    start_id:
        ``id`` value for the first record in this batch.
    count:
        Number of records to generate.
    """
    batch: list[dict[str, Any]] = []
    for i in range(count):
        batch.append(
            {
                "id": start_id + i,
                "customer_id": rng.randint(1, TOTAL_CUSTOMERS),
                "amount": _random_amount(rng),
                "created_at": _random_timestamp(rng),
            }
        )
    return batch


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_orders(session: Session) -> int:
    """Insert 1,000,000 order rows in batches of 50,000.

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
    log.info("Starting order generation: %d rows, batch=%d", TOTAL_ORDERS, BATCH_SIZE)

    rng = random.Random(42)

    inserted = 0

    with tqdm(total=TOTAL_ORDERS, desc="Orders    ", unit="row") as progress:
        for batch_start in range(0, TOTAL_ORDERS, BATCH_SIZE):
            count = min(BATCH_SIZE, TOTAL_ORDERS - batch_start)
            start_id = batch_start + 1

            batch = _build_batch(rng, start_id, count)
            try:
                session.bulk_insert_mappings(Order, batch)  # type: ignore[arg-type]
                session.commit()
            except Exception:
                session.rollback()
                log.exception(
                    "Batch failed (order ids %d–%d); rolled back.",
                    start_id,
                    start_id + count - 1,
                )
                raise

            inserted += count
            progress.update(count)

            del batch
            gc.collect()

    log.info("Order generation complete: %d rows inserted.", inserted)
    return inserted
