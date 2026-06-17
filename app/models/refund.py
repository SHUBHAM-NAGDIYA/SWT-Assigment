"""ORM model for the ``refunds`` table."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.order import Order


class Refund(Base):
    """Represents a refund issued against an order.

    A single order may have multiple partial refunds; the schema does not
    enforce that the sum of refunds cannot exceed the order amount – that
    constraint belongs in the service layer.

    Indexes
    -------
    ix_refunds_order_id
        Covers ``WHERE order_id = ?`` look-ups when loading refunds for a
        given order.
    ix_refunds_created_at
        Covers date-range aggregations (e.g. daily refund totals).
    """

    __tablename__ = "refunds"

    __table_args__ = (
        Index("ix_refunds_order_id", "order_id"),
        Index("ix_refunds_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #

    order: Mapped[Order] = relationship("Order", back_populates="refunds")

    def __repr__(self) -> str:
        return f"<Refund id={self.id} order_id={self.order_id} amount={self.refund_amount}>"
