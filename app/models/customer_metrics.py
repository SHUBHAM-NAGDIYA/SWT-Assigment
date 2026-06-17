"""ORM model for the ``customer_metrics`` pre-aggregated table."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.customer import Customer


class CustomerMetrics(Base):
    """Pre-aggregated lifetime metrics for a single customer.

    One row exists per customer (1-to-1 with ``customers``).  The table is
    updated incrementally as orders are ingested, so analytics endpoints can
    sort or filter on ``total_spend`` or ``order_count`` without aggregating
    the full ``orders`` table.

    Indexes
    -------
    ix_customer_metrics_total_spend_desc
        Supports "top-N customers by spend" queries, which are common in
        analytics dashboards.  The descending direction matches the
        ``ORDER BY total_spend DESC`` used in such queries, allowing
        PostgreSQL to avoid a sort step.
    """

    __tablename__ = "customer_metrics"

    __table_args__ = (
        Index(
            "ix_customer_metrics_total_spend_desc",
            "total_spend",
            postgresql_ops={"total_spend": "DESC"},
        ),
    )

    customer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("customers.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    order_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_spend: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #

    customer: Mapped[Customer] = relationship(
        "Customer",
        back_populates="metrics",
    )

    def __repr__(self) -> str:
        return (
            f"<CustomerMetrics customer_id={self.customer_id} "
            f"order_count={self.order_count} total_spend={self.total_spend}>"
        )
