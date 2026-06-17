"""ORM model for the ``orders`` table."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.refund import Refund


class Order(Base):
    """Represents a single customer order / transaction.

    Indexes
    -------
    ix_orders_customer_id
        Speeds up ``WHERE customer_id = ?`` look-ups used by per-customer
        analytics.
    ix_orders_created_at
        Speeds up date-range scans for daily / monthly revenue queries.
    ix_orders_customer_id_created_at  (composite)
        Covers queries that filter on both customer and date – e.g. "all
        orders for customer X in the last 30 days."  Column order (customer
        first) matches the most selective predicate first.
    """

    __tablename__ = "orders"

    __table_args__ = (
        Index("ix_orders_customer_id", "customer_id"),
        Index("ix_orders_created_at", "created_at"),
        Index("ix_orders_customer_id_created_at", "customer_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # NUMERIC(12, 2) supports order amounts up to 9,999,999,999.99 –
    # precise decimal arithmetic avoids floating-point rounding errors.
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #

    customer: Mapped[Customer] = relationship("Customer", back_populates="orders")

    refunds: Mapped[list[Refund]] = relationship(
        "Refund",
        back_populates="order",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Order id={self.id} customer_id={self.customer_id} amount={self.amount}>"
