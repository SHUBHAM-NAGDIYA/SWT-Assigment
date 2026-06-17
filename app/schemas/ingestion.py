"""Pydantic schemas for the ingestion endpoints.

Kept in a dedicated module so they can evolve independently of the mock
schemas and remain easy to locate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.core.ingestion_state import IngestionStatus


class IngestionStartResponse(BaseModel):
    """Response body for ``POST /ingestion/start``."""

    message: str = Field(..., description="Human-readable confirmation message.")
    status: IngestionStatus = Field(..., description="New pipeline status.")

    model_config = {"from_attributes": True}


class IngestionStatusResponse(BaseModel):
    """Response body for ``GET /ingestion/status``.

    All counter fields reflect the number of rows **successfully written**
    to the database (after conflict resolution), not the number fetched from
    the mock API.
    """

    status: IngestionStatus = Field(..., description="Current pipeline lifecycle state.")
    customers_processed: int = Field(
        ..., ge=0, description="Customers written to the DB so far."
    )
    orders_processed: int = Field(
        ..., ge=0, description="Orders written to the DB so far."
    )
    refunds_processed: int = Field(
        ..., ge=0, description="Refunds written to the DB so far."
    )
    started_at: Optional[datetime] = Field(
        None, description="UTC timestamp when the current/last run began."
    )
    finished_at: Optional[datetime] = Field(
        None, description="UTC timestamp when the current/last run ended."
    )
    error_detail: Optional[str] = Field(
        None, description="Error message if status is 'error', else null."
    )

    model_config = {"from_attributes": True}
