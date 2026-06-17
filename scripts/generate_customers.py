"""Customer data generator.

Generates 100,000 reproducible customer rows and inserts them into the
``customers`` table in batches of 10,000 using
``Session.bulk_insert_mappings``.

Reproducibility
---------------
Both ``random`` and ``Faker`` are seeded with ``42`` before any data is
produced.  Re-running the script against an empty table always yields the
same rows in the same order.

Memory model
------------
Only one batch (10,000 dicts) is held in memory at a time.  After each
``bulk_insert_mappings`` call the list is explicitly deleted and garbage-
collected before the next batch is built.
"""

from __future__ import annotations

import gc
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from faker import Faker
from sqlalchemy.orm import Session
from tqdm import tqdm

from app.models.customer import Customer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOTAL_CUSTOMERS: int = 100_000
BATCH_SIZE: int = 10_000

# Customers were registered at some point in the last two years.
_NOW = datetime.now(tz=timezone.utc)
_TWO_YEARS_AGO = _NOW - timedelta(days=730)
_WINDOW_SECONDS: int = int((_NOW - _TWO_YEARS_AGO).total_seconds())

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _random_timestamp(rng: random.Random) -> datetime:
    """Return a random UTC timestamp within the last two years."""
    offset = rng.randint(0, _WINDOW_SECONDS)
    return _TWO_YEARS_AGO + timedelta(seconds=offset)


def _build_batch(
    fake: Faker,
    rng: random.Random,
    start_id: int,
    count: int,
) -> list[dict[str, Any]]:
    """Build *count* customer mapping dicts starting at *start_id*.

    Parameters
    ----------
    fake:
        A seeded ``Faker`` instance used for name and email generation.
    rng:
        A seeded ``random.Random`` instance used for timestamp generation.
    start_id:
        The ``id`` value assigned to the first record in this batch.
    count:
        Number of records to generate (may be less than ``BATCH_SIZE`` for
        the final partial batch).

    Returns
    -------
    list[dict[str, Any]]
        Ready-to-insert column-value mappings accepted by
        ``bulk_insert_mappings``.
    """
    batch: list[dict[str, Any]] = []
    for i in range(count):
        customer_id = start_id + i
        # Append the id to the email local-part to guarantee uniqueness even
        # when Faker happens to produce the same name twice.
        email = f"{fake.user_name()}.{customer_id}@{fake.domain_name()}"
        batch.append(
            {
                "id": customer_id,
                "name": fake.name(),
                "email": email,
                "created_at": _random_timestamp(rng),
            }
        )
    return batch


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_customers(session: Session) -> int:
    """Insert 100,000 customer rows in batches of 10,000.

    Parameters
    ----------
    session:
        An active SQLAlchemy ``Session``.  The caller is responsible for
        closing the session; this function commits after every batch.

    Returns
    -------
    int
        Total number of rows successfully inserted.

    Raises
    ------
    Exception
        Any database error triggers a rollback before re-raising so the
        session is left in a clean state.
    """
    log.info("Starting customer generation: %d rows, batch=%d", TOTAL_CUSTOMERS, BATCH_SIZE)

    # Seed both PRNG sources *here* so this function is self-contained and
    # calling it always produces the same data regardless of what ran before.
    fake = Faker()
    Faker.seed(42)
    rng = random.Random(42)

    inserted = 0
    batches = range(0, TOTAL_CUSTOMERS, BATCH_SIZE)

    with tqdm(total=TOTAL_CUSTOMERS, desc="Customers", unit="row") as progress:
        for batch_start in batches:
            count = min(BATCH_SIZE, TOTAL_CUSTOMERS - batch_start)
            start_id = batch_start + 1  # 1-based surrogate keys

            batch = _build_batch(fake, rng, start_id, count)
            try:
                session.bulk_insert_mappings(Customer, batch)  # type: ignore[arg-type]
                session.commit()
            except Exception:
                session.rollback()
                log.exception(
                    "Batch failed (customer ids %d–%d); rolled back.",
                    start_id,
                    start_id + count - 1,
                )
                raise

            inserted += count
            progress.update(count)

            # Explicitly release batch memory before the next allocation.
            del batch
            gc.collect()

    log.info("Customer generation complete: %d rows inserted.", inserted)
    return inserted
