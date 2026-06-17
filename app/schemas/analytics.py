"""Pydantic response schemas for the analytics endpoints (Phase 9).

Each schema exposes only the fields the API contract requires, matching the
narrow-schema convention used throughout ``app/schemas`` (see ``mock.py`` and
``aggregates.py``). All amount fields are ``Decimal`` to match the
``NUMERIC(12, 2)`` / ``NUMERIC(15, 2)`` columns they are derived from and to
avoid floating-point rounding errors when FastAPI serialises the response.

``model_config = ConfigDict(from_attributes=True)`` lets every schema accept
either a SQLAlchemy ORM/Row instance or a plain object with matching
attributes (e.g. a ``NamedTuple`` row built by the repository layer).
"""

from __future__ import annotations

from datetime import date as Date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Single-value summary endpoints
# ---------------------------------------------------------------------------


class TotalOrdersResponse(BaseModel):
    """Response body for ``GET /analytics/total-orders``."""

    model_config = ConfigDict(from_attributes=True)

    total_orders: int = Field(..., ge=0, description="Total number of orders across all time.")


class TotalRevenueResponse(BaseModel):
    """Response body for ``GET /analytics/total-revenue``."""

    model_config = ConfigDict(from_attributes=True)

    total_revenue: Decimal = Field(
        ..., ge=0, description="Sum of all order amounts (gross revenue), across all time."
    )


class TotalRefundsResponse(BaseModel):
    """Response body for ``GET /analytics/total-refunds``."""

    model_config = ConfigDict(from_attributes=True)

    total_refunds: Decimal = Field(
        ..., ge=0, description="Sum of all refund amounts, across all time."
    )


class NetRevenueResponse(BaseModel):
    """Response body for ``GET /analytics/net-revenue``."""

    model_config = ConfigDict(from_attributes=True)

    net_revenue: Decimal = Field(
        ..., description="Total revenue minus total refunds, across all time."
    )


class AverageOrderValueResponse(BaseModel):
    """Response body for ``GET /analytics/average-order-value``."""

    model_config = ConfigDict(from_attributes=True)

    average_order_value: Decimal = Field(
        ...,
        ge=0,
        description="Total revenue divided by total order count. 0 when there are no orders.",
    )


class RepeatCustomerRevenueResponse(BaseModel):
    """Response body for ``GET /analytics/repeat-customer-revenue``."""

    model_config = ConfigDict(from_attributes=True)

    repeat_customer_revenue: Decimal = Field(
        ...,
        description=(
            "Net revenue (orders minus refunds) attributable to customers "
            "who have placed more than one order."
        ),
    )


# ---------------------------------------------------------------------------
# List endpoints
# ---------------------------------------------------------------------------


class RevenueTrendPoint(BaseModel):
    """A single day's revenue figure, as returned by ``revenue-trends``."""

    model_config = ConfigDict(from_attributes=True)

    date: Date = Field(..., description="Calendar day (UTC).")
    revenue: Decimal = Field(..., description="Net revenue (gross revenue minus refunds) for this day.")


class TopCustomerEntry(BaseModel):
    """A single customer's ranking entry, as returned by ``top-customers``."""

    model_config = ConfigDict(from_attributes=True)

    customer_id: int = Field(..., description="FK → customers.id.")
    total_spend: Decimal = Field(..., description="Lifetime sum of order amounts (gross).")
    order_count: int = Field(..., ge=0, description="Lifetime number of orders placed.")
