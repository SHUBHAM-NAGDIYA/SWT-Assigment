"""Generic pagination envelope used by every mock endpoint.

Using a Generic allows a single ``PaginatedResponse[T]`` type to serve all
three endpoints while still giving FastAPI and Pydantic enough information
to generate accurate OpenAPI schemas for each concrete response type.
"""

from __future__ import annotations

import math
from typing import Generic, Sequence, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard envelope returned by every paginated list endpoint.

    Attributes
    ----------
    page:
        Current (1-based) page number, echoed from the request.
    page_size:
        Number of items requested per page, echoed from the request.
    total:
        Exact row count for the full (un-paginated) result set.
    total_pages:
        ``ceil(total / page_size)`` — computed by the service layer so
        clients never need to do the arithmetic themselves.
    data:
        The slice of records for this page.
    """

    page: int = Field(..., ge=1, description="Current page number (1-based).")
    page_size: int = Field(..., ge=1, le=1000, description="Items per page.")
    total: int = Field(..., ge=0, description="Total number of matching records.")
    total_pages: int = Field(..., ge=0, description="Total number of pages.")
    data: Sequence[T]

    model_config = {"from_attributes": True}

    @classmethod
    def build(
        cls,
        *,
        page: int,
        page_size: int,
        total: int,
        data: Sequence[T],
    ) -> "PaginatedResponse[T]":
        """Factory that computes ``total_pages`` automatically.

        Parameters
        ----------
        page:
            Current 1-based page index.
        page_size:
            Number of items per page (already validated ≥ 1).
        total:
            Total row count from the database.
        data:
            The current page's records.
        """
        total_pages = math.ceil(total / page_size) if page_size > 0 else 0
        return cls(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            data=data,
        )
