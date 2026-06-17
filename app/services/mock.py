"""Service layer for the mock endpoints.

Responsibilities
----------------
* Translate page/page_size parameters into ``offset``/``limit`` values.
* Orchestrate repository calls (count + list_page).
* Assemble ``PaginatedResponse`` envelopes.
* Remain ignorant of HTTP details (no ``Request``, ``Response``, or
  ``HTTPException`` imports here).

Why a separate service layer?
------------------------------
For simple CRUD this layer might look like thin wrappers around the
repository.  Its value becomes clear when:
  * Business rules evolve (e.g. filtering out soft-deleted records, applying
    role-based column visibility, enriching results with computed fields).
  * The same logic needs to be called from a background task or CLI script,
    not just an HTTP handler.
  * Unit tests want to mock the repository without spinning up a database.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.repositories.mock import CustomerRepository, OrderRepository, RefundRepository
from app.schemas.mock import CustomerSchema, OrderSchema, RefundSchema
from app.schemas.pagination import PaginatedResponse


class MockService:
    """Orchestrates data retrieval for the three mock list endpoints."""

    def __init__(self, session: Session) -> None:
        self._customers = CustomerRepository(session)
        self._orders = OrderRepository(session)
        self._refunds = RefundRepository(session)

    # ---------------------------------------------------------------------- #
    # Internal helpers                                                         #
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _to_offset(page: int, page_size: int) -> int:
        """Convert 1-based ``page`` + ``page_size`` to a SQL OFFSET value."""
        return (page - 1) * page_size

    # ---------------------------------------------------------------------- #
    # Public API                                                               #
    # ---------------------------------------------------------------------- #

    def get_customers(
        self,
        *,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[CustomerSchema]:
        """Return a paginated list of customers.

        Two queries are issued:
        1. ``SELECT COUNT(*) FROM customers``   — for ``total`` / ``total_pages``.
        2. ``SELECT … FROM customers ORDER BY id LIMIT … OFFSET …``

        Parameters
        ----------
        page:
            1-based page index (already validated ≥ 1 by the router).
        page_size:
            Page size (already validated 1 ≤ page_size ≤ 1000 by the router).
        """
        total = self._customers.count()
        rows = self._customers.list_page(
            offset=self._to_offset(page, page_size),
            limit=page_size,
        )
        data = [CustomerSchema.model_validate(row) for row in rows]
        return PaginatedResponse[CustomerSchema].build(
            page=page,
            page_size=page_size,
            total=total,
            data=data,
        )

    def get_orders(
        self,
        *,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[OrderSchema]:
        """Return a paginated list of orders.

        Parameters
        ----------
        page:
            1-based page index.
        page_size:
            Page size.
        """
        total = self._orders.count()
        rows = self._orders.list_page(
            offset=self._to_offset(page, page_size),
            limit=page_size,
        )
        data = [OrderSchema.model_validate(row) for row in rows]
        return PaginatedResponse[OrderSchema].build(
            page=page,
            page_size=page_size,
            total=total,
            data=data,
        )

    def get_refunds(
        self,
        *,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[RefundSchema]:
        """Return a paginated list of refunds.

        Parameters
        ----------
        page:
            1-based page index.
        page_size:
            Page size.
        """
        total = self._refunds.count()
        rows = self._refunds.list_page(
            offset=self._to_offset(page, page_size),
            limit=page_size,
        )
        data = [RefundSchema.model_validate(row) for row in rows]
        return PaginatedResponse[RefundSchema].build(
            page=page,
            page_size=page_size,
            total=total,
            data=data,
        )
