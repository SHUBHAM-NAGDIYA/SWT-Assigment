"""Repository layer for the ingestion pipeline.

Responsibilities
----------------
* Accept pre-validated batches of plain dicts from the service layer.
* Issue efficient bulk ``INSERT … ON CONFLICT DO NOTHING`` statements.
* Return the number of rows actually inserted (conflicts excluded).
* Know nothing about HTTP, pagination, or the mock API.

Idempotency via ON CONFLICT DO NOTHING
---------------------------------------
PostgreSQL's ``INSERT … ON CONFLICT DO NOTHING`` is the cleanest way to
make ingestion idempotent:

* No ``SELECT`` round-trip before each insert (avoids the TOCTOU race).
* Partial batches that fail mid-way can be retried safely — already-inserted
  rows are silently skipped on the next attempt.
* The ``rowcount`` on the result reflects only newly inserted rows, so
  progress counters stay accurate.

Why ``session.execute(insert(...).values(...))`` instead of
``session.bulk_insert_mappings``?
------------------------------------------
``bulk_insert_mappings`` does not support ``on_conflict_do_nothing()``
because it bypasses the SQLAlchemy Core expression layer.  The SQLAlchemy
2.0 ``insert()`` construct supports the full ``ON CONFLICT`` clause via
``dialect_kwargs`` (PostgreSQL-specific) and returns accurate ``rowcount``.

Batch size is owned by the service layer; this repository is size-agnostic.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.order import Order
from app.models.refund import Refund

log = logging.getLogger(__name__)


class IngestionRepository:
    """Handles bulk idempotent writes for the three ingestion entities."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ---------------------------------------------------------------------- #
    # Internal helper                                                          #
    # ---------------------------------------------------------------------- #

    def _bulk_insert_ignore(
        self,
        model: type,
        rows: list[dict[str, Any]],
    ) -> int:
        """Insert *rows* into *model*'s table, ignoring duplicate PKs.

        Uses PostgreSQL's ``INSERT … ON CONFLICT (id) DO NOTHING`` so that
        re-running ingestion never creates duplicates and never raises a
        ``UniqueViolation`` error.

        Parameters
        ----------
        model:
            The SQLAlchemy ORM model class (``Customer``, ``Order``, …).
        rows:
            List of column-value dicts.  All dicts must have the same keys.

        Returns
        -------
        int
            Number of rows actually inserted (conflicts are excluded from
            the count by PostgreSQL and reflected in ``cursor.rowcount``).
        """
        if not rows:
            return 0

        stmt = pg_insert(model).values(rows).on_conflict_do_nothing(index_elements=["id"])
        result = self._session.execute(stmt)
        # ``rowcount`` is -1 for statements that don't naturally return a
        # count (rare with psycopg3, but guard defensively).
        inserted = result.rowcount if result.rowcount >= 0 else len(rows)
        return inserted

    # ---------------------------------------------------------------------- #
    # Public API                                                               #
    # ---------------------------------------------------------------------- #

    def bulk_insert_customers(self, rows: list[dict[str, Any]]) -> int:
        """Insert a batch of customer rows, skipping existing IDs.

        Parameters
        ----------
        rows:
            Each dict must contain ``id``, ``name``, ``email``,
            ``created_at``.

        Returns
        -------
        int
            Rows inserted (conflicts skipped).
        """
        inserted = self._bulk_insert_ignore(Customer, rows)
        self._session.commit()
        log.debug("Customers batch: %d inserted (%d skipped).", inserted, len(rows) - inserted)
        return inserted

    def bulk_insert_orders(self, rows: list[dict[str, Any]]) -> int:
        """Insert a batch of order rows, skipping existing IDs.

        Parameters
        ----------
        rows:
            Each dict must contain ``id``, ``customer_id``, ``amount``,
            ``created_at``.

        Returns
        -------
        int
            Rows inserted (conflicts skipped).
        """
        inserted = self._bulk_insert_ignore(Order, rows)
        self._session.commit()
        log.debug("Orders batch: %d inserted (%d skipped).", inserted, len(rows) - inserted)
        return inserted

    def bulk_insert_refunds(self, rows: list[dict[str, Any]]) -> int:
        """Insert a batch of refund rows, skipping existing IDs.

        Parameters
        ----------
        rows:
            Each dict must contain ``id``, ``order_id``, ``refund_amount``,
            ``created_at``.

        Returns
        -------
        int
            Rows inserted (conflicts skipped).
        """
        inserted = self._bulk_insert_ignore(Refund, rows)
        self._session.commit()
        log.debug("Refunds batch: %d inserted (%d skipped).", inserted, len(rows) - inserted)
        return inserted
