"""HTTP router for the ``/ingestion`` endpoint group.

Endpoints
---------
POST /ingestion/start
    Launches the ingestion pipeline as a background task and returns
    immediately (HTTP 202 Accepted).  Rejects concurrent runs with HTTP 409.

GET /ingestion/status
    Returns a snapshot of the current ingestion state: lifecycle status,
    per-entity row counters, timestamps, and any error message.

Background task pattern
-----------------------
``POST /ingestion/start`` uses FastAPI's ``BackgroundTasks`` to launch
``run_ingestion`` *after* the HTTP response has been sent.  This means:

  * The caller gets an immediate 202 response — no long-polling required.
  * The ingestion runs in the same process / event loop as the API server.
  * Progress is visible via ``GET /ingestion/status`` while the pipeline runs.

This is appropriate for a single-worker development setup.  In production,
move the background work to a proper task queue (Celery + Redis or similar)
so it survives worker restarts and can be distributed across machines.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.core.database import SessionLocal
from app.core.ingestion_state import IngestionStatus, ingestion_state
from app.schemas.ingestion import IngestionStartResponse, IngestionStatusResponse
from app.services.ingestion import run_ingestion

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ingestion",
    tags=["ingestion"],
)


# ---------------------------------------------------------------------------
# POST /ingestion/start
# ---------------------------------------------------------------------------

@router.post(
    "/start",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestionStartResponse,
    summary="Trigger the ingestion pipeline",
    description=(
        "Launches the full ingestion pipeline (customers → orders → refunds) "
        "as a background task and returns immediately.\n\n"
        "Returns **HTTP 409** if an ingestion is already running.\n\n"
        "Poll ``GET /ingestion/status`` to monitor progress."
    ),
)
async def start_ingestion(background_tasks: BackgroundTasks) -> IngestionStartResponse:
    """Start the ingestion pipeline in the background.

    The pipeline fetches all records from the mock API and bulk-inserts them
    into PostgreSQL using ``INSERT … ON CONFLICT DO NOTHING``, making it
    safe to run multiple times.

    Raises
    ------
    HTTPException (409)
        If an ingestion pipeline is already running.
    """
    if ingestion_state.is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An ingestion pipeline is already running. "
                "Poll GET /ingestion/status to monitor progress."
            ),
        )

    log.info("Ingestion start requested — scheduling background task.")

    # ``BackgroundTasks.add_task`` schedules the coroutine to run after the
    # response is sent.  FastAPI awaits background tasks sequentially after
    # the response body is delivered.
    background_tasks.add_task(run_ingestion, SessionLocal)

    return IngestionStartResponse(
        message="Ingestion pipeline started successfully.",
        status=IngestionStatus.RUNNING,
    )


# ---------------------------------------------------------------------------
# GET /ingestion/status
# ---------------------------------------------------------------------------

@router.get(
    "/status",
    response_model=IngestionStatusResponse,
    summary="Query ingestion progress",
    description=(
        "Returns the current state of the ingestion pipeline including "
        "lifecycle status, per-entity row counters, start/finish timestamps, "
        "and any error message from the most recent run."
    ),
)
def get_ingestion_status() -> IngestionStatusResponse:
    """Return a snapshot of the current ingestion state.

    This endpoint is synchronous (no ``async``) because it only reads
    from the in-memory ``IngestionState`` object — no I/O required.
    FastAPI runs synchronous handlers in the thread-pool executor
    automatically, keeping the event loop free.

    Returns
    -------
    IngestionStatusResponse
        Live snapshot of progress counters and lifecycle state.
    """
    return IngestionStatusResponse(
        status=ingestion_state.status,
        customers_processed=ingestion_state.customers_processed,
        orders_processed=ingestion_state.orders_processed,
        refunds_processed=ingestion_state.refunds_processed,
        started_at=ingestion_state.started_at,
        finished_at=ingestion_state.finished_at,
        error_detail=ingestion_state.error_detail,
    )
