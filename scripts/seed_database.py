"""Database seeder — orchestrates the full seeding pipeline.

Execution order
---------------
1. ``generate_customers`` — 100,000 rows, batch 10,000
2. ``generate_orders``    — 1,000,000 rows, batch 50,000
3. ``generate_refunds``   — 200,000 rows, batch 20,000

Each phase is self-contained and commits its own batches.  A failure in any
phase prints the error, rolls back the current in-flight batch (handled by
the generator itself), and exits with a non-zero code so CI/CD pipelines can
detect the failure.

Usage
-----
Run from the project root so that ``app.*`` imports resolve correctly::

    python -m scripts.seed_database

Or, if the project root is on PYTHONPATH::

    python scripts/seed_database.py

Environment
-----------
``DATABASE_URL`` is read from ``.env`` via ``app.core.config.settings``.
No additional environment variables are required.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from textwrap import dedent

from sqlalchemy import func, text

from app.core.database import SessionLocal
from scripts.generate_customers import generate_customers
from scripts.generate_orders import generate_orders
from scripts.generate_refunds import generate_refunds

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------

def _validate(session) -> dict[str, int]:  # type: ignore[type-arg]
    """Return live row counts from the database for the three seeded tables.

    Uses ``COUNT(*)`` rather than relying on the return values from the
    generators so that the validation reflects what is actually persisted.
    """
    counts: dict[str, int] = {}
    for table in ("customers", "orders", "refunds"):
        row = session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        counts[table] = int(row)
    return counts


def _print_summary(
    counts: dict[str, int],
    elapsed_seconds: float,
) -> None:
    """Print a formatted validation summary to stdout."""
    separator = "─" * 44
    print(
        dedent(
            f"""
            {separator}
             Database Seeding — Validation Summary
            {separator}
             {'Table':<20} {'Rows':>10}  {'Status'}
            {separator}
             {'customers':<20} {counts['customers']:>10,}  {'✓ OK' if counts['customers'] == 100_000 else '✗ MISMATCH'}
             {'orders':<20} {counts['orders']:>10,}  {'✓ OK' if counts['orders'] == 1_000_000 else '✗ MISMATCH'}
             {'refunds':<20} {counts['refunds']:>10,}  {'✓ OK' if counts['refunds'] == 200_000 else '✗ MISMATCH'}
            {separator}
             Total rows inserted : {sum(counts.values()):>12,}
             Elapsed time        : {elapsed_seconds:>11.1f}s
            {separator}
            """
        ).strip()
    )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def seed() -> None:
    """Run the full seeding pipeline in a single database session.

    A *new* session is opened for the entire pipeline.  Each generator
    commits its own batches, so partial progress is preserved if a later
    phase fails.  The session is always closed in the ``finally`` block.
    """
    log.info("═" * 50)
    log.info("  Seeding pipeline started at %s", datetime.now(tz=timezone.utc).isoformat())
    log.info("═" * 50)

    session = SessionLocal()
    t0 = time.perf_counter()

    try:
        # ------------------------------------------------------------------ #
        # Phase 1 — Customers                                                 #
        # ------------------------------------------------------------------ #
        log.info("Phase 1/3 — Customers")
        generate_customers(session)

        # ------------------------------------------------------------------ #
        # Phase 2 — Orders                                                    #
        # ------------------------------------------------------------------ #
        log.info("Phase 2/3 — Orders")
        generate_orders(session)

        # ------------------------------------------------------------------ #
        # Phase 3 — Refunds                                                   #
        # ------------------------------------------------------------------ #
        log.info("Phase 3/3 — Refunds")
        generate_refunds(session)

    except Exception as exc:
        log.error("Seeding pipeline failed: %s", exc, exc_info=True)
        sys.exit(1)

    finally:
        elapsed = time.perf_counter() - t0

        # Always validate from the DB (even after partial failure) so the
        # operator knows exactly how many rows landed.
        try:
            counts = _validate(session)
            _print_summary(counts, elapsed)
        except Exception:
            log.exception("Validation query failed — session may be unusable.")
        finally:
            session.close()
            log.info("Session closed.")

    log.info("Seeding pipeline complete (%.1fs).", elapsed)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    seed()
