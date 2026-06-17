"""Pydantic schemas for the aggregate processing endpoints.

Kept narrow and explicit: each schema exposes exactly the fields the
API contract requires, nothing more.  Future columns added to the ORM
models are not leaked until a deliberate schema change is made here.
"""

from __future__ import annotations

from datetime import  datetime
from datetime import date as Date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Aggregate status / lifecycle
# ---------------------------------------------------------------------------


class AggregateStatus(str, Enum):
    """Lifecycle states of the aggregate refresh job."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Trigger response
# ---------------------------------------------------------------------------


class AggregateRefreshResponse(BaseModel):
    """Response body for ``POST /aggregates/refresh``."""

    message: str = Field(..., description="Human-readable confirmation.")
    status: AggregateStatus = Field(..., description="New job lifecycle state.")

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Status response
# ---------------------------------------------------------------------------


class AggregateStatusResponse(BaseModel):
    """Response body for ``GET /aggregates/status``.

    All counter fields are updated atomically after each phase completes,
    not after individual row writes, because both aggregate refreshes are
    single SQL statements (not batched loops).
    """

    status: AggregateStatus = Field(..., description="Current lifecycle state.")
    daily_revenue_rows: int = Field(
        ...,
        ge=0,
        description="Rows written to daily_revenue in the last run.",
    )
    customer_metrics_rows: int = Field(
        ...,
        ge=0,
        description="Rows written to customer_metrics in the last run.",
    )
    started_at: Optional[datetime] = Field(
        None,
        description="UTC timestamp when the current/last run began.",
    )
    finished_at: Optional[datetime] = Field(
        None,
        description="UTC timestamp when the current/last run ended.",
    )
    duration_seconds: Optional[float] = Field(
        None,
        ge=0.0,
        description="Wall-clock time of the last completed run, in seconds.",
    )
    error_detail: Optional[str] = Field(
        None,
        description="Error message if status is 'error', else null.",
    )

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Aggregate data schemas (used by analytics read endpoints)
# ---------------------------------------------------------------------------


class DailyRevenueSchema(BaseModel):
    """Outbound representation of a single daily_revenue row."""

    model_config = ConfigDict(from_attributes=True)

    date: Date = Field(..., description="Calendar day (UTC).")
    total_orders: int = Field(..., description="Number of orders placed on this day.")
    total_revenue: Decimal = Field(..., description="Gross revenue on this day.")
    total_refunds: Decimal = Field(..., description="Total refunds issued on this day.")
    net_revenue: Decimal = Field(..., description="Gross revenue minus refunds.")


class CustomerMetricsSchema(BaseModel):
    """Outbound representation of a single customer_metrics row."""

    model_config = ConfigDict(from_attributes=True)

    customer_id: int = Field(..., description="FK → customers.id.")
    order_count: int = Field(..., description="Lifetime number of orders.")
    total_spend: Decimal = Field(..., description="Lifetime sum of order amounts.")
