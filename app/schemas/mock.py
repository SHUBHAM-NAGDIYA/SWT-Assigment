"""Pydantic response schemas for the mock endpoints.

Each schema exposes only the columns that the API contract requires.
Keeping schemas narrow:
  * prevents accidental leakage of internal fields added later to the ORM
    model (e.g. soft-delete flags, internal audit columns).
  * reduces serialisation overhead — Pydantic only processes what it sees.

``model_config = {"from_attributes": True}`` lets Pydantic read values
directly from SQLAlchemy ORM instances (row.id, row.name, …) without
requiring an explicit ``.model_validate(row.__dict__)`` call.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CustomerSchema(BaseModel):
    """Outbound representation of a single customer row."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Surrogate primary key.")
    name: str = Field(..., description="Customer display name.")
    email: str = Field(..., description="Unique customer email address.")
    created_at: datetime = Field(..., description="UTC timestamp of account creation.")


class OrderSchema(BaseModel):
    """Outbound representation of a single order row."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Surrogate primary key.")
    customer_id: int = Field(..., description="FK → customers.id.")
    amount: Decimal = Field(..., description="Order amount (NUMERIC 12,2).")
    created_at: datetime = Field(..., description="UTC timestamp of order creation.")


class RefundSchema(BaseModel):
    """Outbound representation of a single refund row."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Surrogate primary key.")
    order_id: int = Field(..., description="FK → orders.id.")
    refund_amount: Decimal = Field(..., description="Refunded amount (NUMERIC 12,2).")
    created_at: datetime = Field(..., description="UTC timestamp of refund creation.")
