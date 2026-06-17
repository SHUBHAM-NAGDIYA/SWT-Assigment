"""Database engine, session factory, declarative base, and FastAPI dependency.

Design notes
------------
* Uses SQLAlchemy 2.0 declarative style (``DeclarativeBase``, ``Mapped``,
  ``mapped_column``) throughout.
* The engine is created once at module import time and reused for the
  lifetime of the process.  Connection pool settings are sized for an
  analytics workload: read-heavy, moderate concurrency, occasional long
  aggregate queries.
* ``SessionLocal`` is a plain synchronous session factory.  All sessions are
  opened with ``autocommit=False`` and ``autoflush=False`` so that callers
  retain explicit control over transaction boundaries.
* ``get_db`` is a FastAPI dependency that yields one session per request and
  guarantees closure even when an exception escapes the route handler.
"""

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models.

    Every model that inherits from ``Base`` is automatically registered with
    ``Base.metadata``, which Alembic's ``--autogenerate`` uses to diff the
    live schema against the ORM definition.

    The class carries no columns or constraints of its own so that individual
    models remain fully explicit about their schema.
    """


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _build_engine() -> Engine:
    """Construct and return the SQLAlchemy ``Engine``.

    Pool sizing rationale
    ~~~~~~~~~~~~~~~~~~~~~
    * ``pool_size=10`` – keeps 10 connections warm at all times.  Enough for
      typical FastAPI worker concurrency without over-subscribing PostgreSQL.
    * ``max_overflow=20`` – allows bursts up to 30 total connections before
      new requests block on ``pool_timeout``.
    * ``pool_timeout=30`` – raises ``TimeoutError`` after 30 s rather than
      queuing forever, which would mask a connection-pool saturation problem.
    * ``pool_recycle=1800`` – recycles connections every 30 min so that
      PostgreSQL's ``idle_in_transaction_session_timeout`` and network
      middlebox timeouts never silently kill a pooled connection.
    * ``pool_pre_ping=True`` – issues a cheap ``SELECT 1`` on checkout to
      discard stale connections after a DB restart or network blip.
    """
    engine = create_engine(
        settings.DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
        # Emit generated SQL to the "sqlalchemy.engine" logger.
        # Set the logger level to INFO in development to enable query logging
        # without touching application code.
        echo=False,
    )
    return engine


engine: Engine = _build_engine()
"""Process-wide SQLAlchemy engine.

Do **not** create additional engines.  Import this object wherever a raw
DBAPI connection or engine-level operation is required.
"""

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    # Keep attribute access available after ``session.commit()`` without an
    # implicit re-query.  Callers that need fresh data must call
    # ``session.refresh(obj)`` explicitly.
    expire_on_commit=False,
)
"""Configured session factory.

Instantiate a session directly only in scripts or background tasks::

    with SessionLocal() as db:
        result = db.execute(text("SELECT 1")).scalar()

Inside FastAPI route handlers, use the ``get_db`` dependency instead.
"""


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_db() -> Generator[Session, None, None]:
    """Yield a ``Session`` for the duration of a single HTTP request.

    The session is always closed in the ``finally`` block, regardless of
    whether the route handler raises an exception.  Committing or rolling
    back is the responsibility of the route handler (or a service layer
    called by it).

    Usage::

        from sqlalchemy.orm import Session
        from fastapi import Depends
        from app.core.database import get_db

        @router.get("/example")
        def example_route(db: Session = Depends(get_db)) -> dict[str, Any]:
            row = db.execute(text("SELECT 42 AS answer")).mappings().one()
            return dict(row)
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
