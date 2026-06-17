"""Repository layer for the mock endpoints.

Responsibilities
----------------
* Issue all ORM queries against the database.
* Return plain SQLAlchemy model instances (or lightweight row objects).
* Know nothing about HTTP, pagination math, or response serialisation.

Query design
------------
``load_only``
    Instructs SQLAlchemy to emit a ``SELECT`` that fetches *only* the named
    columns.  This is the ORM equivalent of ``SELECT id, name, email, ...``
    and avoids transferring columns that the API response will never use
    (e.g. relationship-loaded sub-objects, future audit columns).

``execution_options(populate_existing=False)``
    Not set here because we never mutate these objects; the default is safe.

``order_by(Model.id)``
    Deterministic ordering is required for correct OFFSET pagination.
    Without an ORDER BY, PostgreSQL may return rows in any order and a
    record could appear on two different pages (or not at all) as concurrent
    inserts shift the physical page layout.

COUNT query
    A separate ``SELECT COUNT(*)`` is issued for each list request so that
    the envelope can include ``total`` and ``total_pages``.  For a dataset
    of this size (~100k–1M rows) PostgreSQL can answer a plain ``COUNT(*)``
    from the index in well under 100 ms.  If that becomes a bottleneck, the
    service layer can switch to approximate counts via ``pg_class.reltuples``
    without touching the router or schema.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, load_only

from app.models.customer import Customer
from app.models.order import Order
from app.models.refund import Refund


# ---------------------------------------------------------------------------
# Customer repository
# ---------------------------------------------------------------------------


class CustomerRepository:
    """Data-access methods for the ``customers`` table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def count(self) -> int:
        """Return the total number of customer rows."""
        return self._session.scalar(select(func.count()).select_from(Customer)) or 0

    def list_page(self, *, offset: int, limit: int) -> list[Customer]:
        """Return one page of customer rows ordered by primary key.

        Parameters
        ----------
        offset:
            Number of rows to skip (``(page - 1) * page_size``).
        limit:
            Maximum number of rows to return (``page_size``).

        Returns
        -------
        list[Customer]
            Partially-loaded ORM instances.  Only ``id``, ``name``,
            ``email``, and ``created_at`` are hydrated; all other columns
            and relationships are left unloaded.
        """
        stmt = (
            select(Customer)
            .options(
                load_only(
                    Customer.id,
                    Customer.name,
                    Customer.email,
                    Customer.created_at,
                )
            )
            .order_by(Customer.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(stmt))


# ---------------------------------------------------------------------------
# Order repository
# ---------------------------------------------------------------------------


class OrderRepository:
    """Data-access methods for the ``orders`` table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def count(self) -> int:
        """Return the total number of order rows."""
        return self._session.scalar(select(func.count()).select_from(Order)) or 0

    def list_page(self, *, offset: int, limit: int) -> list[Order]:
        """Return one page of order rows ordered by primary key.

        Parameters
        ----------
        offset:
            Number of rows to skip.
        limit:
            Maximum number of rows to return.
        """
        stmt = (
            select(Order)
            .options(
                load_only(
                    Order.id,
                    Order.customer_id,
                    Order.amount,
                    Order.created_at,
                )
            )
            .order_by(Order.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(stmt))


# ---------------------------------------------------------------------------
# Refund repository
# ---------------------------------------------------------------------------


class RefundRepository:
    """Data-access methods for the ``refunds`` table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def count(self) -> int:
        """Return the total number of refund rows."""
        return self._session.scalar(select(func.count()).select_from(Refund)) or 0

    def list_page(self, *, offset: int, limit: int) -> list[Refund]:
        """Return one page of refund rows ordered by primary key.

        Parameters
        ----------
        offset:
            Number of rows to skip.
        limit:
            Maximum number of rows to return.
        """
        stmt = (
            select(Refund)
            .options(
                load_only(
                    Refund.id,
                    Refund.order_id,
                    Refund.refund_amount,
                    Refund.created_at,
                )
            )
            .order_by(Refund.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(stmt))
