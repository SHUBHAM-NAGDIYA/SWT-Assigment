"""HTTP router for the ``/mock`` endpoint group.

This module's only job is HTTP plumbing:
  * Declare routes, HTTP methods, and response models.
  * Validate and coerce query parameters (FastAPI handles this via ``Query``).
  * Instantiate the service with the injected session.
  * Return the service's result directly.

No SQL, no business logic, and no schema construction lives here.

Pagination query parameters
---------------------------
``page``       — 1-based page index, minimum 1.
``page_size``  — rows per page, 1–1000 (default 100).

FastAPI validates these automatically using the ``Query(ge=…, le=…)``
constraints.  Invalid values receive an HTTP 422 Unprocessable Entity
response with a structured JSON body before the handler is ever called.

Response model
--------------
``response_model=PaginatedResponse[XxxSchema]`` instructs FastAPI to:
  1. Validate the returned object against the schema at runtime.
  2. Strip any fields that are not declared in the schema (defence-in-depth).
  3. Generate an accurate JSON-Schema entry in the OpenAPI spec.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.mock import CustomerSchema, OrderSchema, RefundSchema
from app.schemas.pagination import PaginatedResponse
from app.services.mock import MockService

router = APIRouter(
    prefix="/mock",
    tags=["mock"],
)

# ---------------------------------------------------------------------------
# Reusable query-parameter annotations
# ---------------------------------------------------------------------------

# Declaring them once avoids repeating the same ge/le/description in every
# endpoint signature, and keeps all validation rules in a single place.

PageParam = Annotated[
    int,
    Query(ge=1, description="Page number (1-based)."),
]

PageSizeParam = Annotated[
    int,
    Query(ge=1, le=1000, description="Number of items per page (max 1 000)."),
]


# ---------------------------------------------------------------------------
# Dependency: MockService
# ---------------------------------------------------------------------------

def _get_mock_service(db: Session = Depends(get_db)) -> MockService:
    """Construct a ``MockService`` bound to the current request's session.

    Injected via ``Depends`` so FastAPI manages the session lifecycle:
    the session is opened before the handler runs and closed (with rollback
    if needed) when the response is sent.
    """
    return MockService(db)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/customers",
    response_model=PaginatedResponse[CustomerSchema],
    summary="List customers (paginated)",
    description=(
        "Returns a paginated list of customers ordered by ``id``.\n\n"
        "Pagination is LIMIT/OFFSET-based.  For large offsets (late pages) "
        "consider keyset pagination in a future version."
    ),
)
def list_customers(
    page: PageParam = 1,
    page_size: PageSizeParam = 100,
    service: MockService = Depends(_get_mock_service),
) -> PaginatedResponse[CustomerSchema]:
    """Retrieve one page of customer records.

    Parameters
    ----------
    page:
        1-based page index; must be ≥ 1.
    page_size:
        Number of records to return; must be between 1 and 1 000.
    service:
        ``MockService`` instance injected by FastAPI.
    """
    return service.get_customers(page=page, page_size=page_size)


@router.get(
    "/orders",
    response_model=PaginatedResponse[OrderSchema],
    summary="List orders (paginated)",
    description=(
        "Returns a paginated list of orders ordered by ``id``.  "
        "Only ``id``, ``customer_id``, ``amount``, and ``created_at`` "
        "are included in each item."
    ),
)
def list_orders(
    page: PageParam = 1,
    page_size: PageSizeParam = 100,
    service: MockService = Depends(_get_mock_service),
) -> PaginatedResponse[OrderSchema]:
    """Retrieve one page of order records.

    Parameters
    ----------
    page:
        1-based page index; must be ≥ 1.
    page_size:
        Number of records to return; must be between 1 and 1 000.
    service:
        ``MockService`` instance injected by FastAPI.
    """
    return service.get_orders(page=page, page_size=page_size)


@router.get(
    "/refunds",
    response_model=PaginatedResponse[RefundSchema],
    summary="List refunds (paginated)",
    description=(
        "Returns a paginated list of refunds ordered by ``id``.  "
        "``refund_amount`` is always ≤ the corresponding order's ``amount``."
    ),
)
def list_refunds(
    page: PageParam = 1,
    page_size: PageSizeParam = 100,
    service: MockService = Depends(_get_mock_service),
) -> PaginatedResponse[RefundSchema]:
    """Retrieve one page of refund records.

    Parameters
    ----------
    page:
        1-based page index; must be ≥ 1.
    page_size:
        Number of records to return; must be between 1 and 1 000.
    service:
        ``MockService`` instance injected by FastAPI.
    """
    return service.get_refunds(page=page, page_size=page_size)
