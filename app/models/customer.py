"""ORM model for the ``customers`` table."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.customer_metrics import CustomerMetrics
    from app.models.order import Order


class Customer(Base):
    """Represents a customer account.

    Columns
    -------
    id          Surrogate primary key (BIGINT) – supports 100 k+ rows with
                room to grow without integer overflow.
    name        Display name; required.
    email       Unique contact address; used as a natural key in lookups.
    created_at  UTC timestamp of account creation; supplied by the caller
                (not a server default) so that ingested historical data
                preserves its original timestamp.
    """

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #

    orders: Mapped[list[Order]] = relationship(
        "Order",
        back_populates="customer",
        passive_deletes=True,
    )

    metrics: Mapped[CustomerMetrics | None] = relationship(
        "CustomerMetrics",
        back_populates="customer",
        uselist=False,
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Customer id={self.id} email={self.email!r}>"
