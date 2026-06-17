"""ORM model for the ``daily_revenue`` pre-aggregated table."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, BigInteger, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DailyRevenue(Base):
    """Pre-aggregated daily revenue snapshot.

    This table is a materialised summary updated by a scheduled job (e.g.
    nightly ETL or a Celery beat task).  Storing aggregates here avoids
    full table-scans over the million-row ``orders`` table at query time,
    keeping analytics API responses well under the 2-second SLA.

    Columns
    -------
    date            Calendar day (UTC); primary key – one row per day.
    total_orders    Number of orders placed on this day.
    total_revenue   Gross revenue (sum of order amounts) on this day.
    total_refunds   Total refund amounts issued on this day.
    net_revenue     ``total_revenue - total_refunds``; stored redundantly
                    for fast retrieval without on-the-fly arithmetic.
    """

    __tablename__ = "daily_revenue"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    total_orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_revenue: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    total_refunds: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    net_revenue: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<DailyRevenue date={self.date} net_revenue={self.net_revenue}>"
        )
