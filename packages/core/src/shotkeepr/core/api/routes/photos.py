"""Importazioni e catalogo locale protetti dal token dell'API."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.api.auth import require_token
from shotkeepr.core.api.import_jobs import ImportBusyError, ImportJobs
from shotkeepr.core.api.photo_schemas import (
    ApiError,
    ImportJobOut,
    ImportRequest,
    SessionOut,
    ShotOut,
    ShotPageOut,
)
from shotkeepr.core.application.exposure import ExposureService
from shotkeepr.core.application.grouping import GroupingService
from shotkeepr.core.application.review import ReviewService
from shotkeepr.core.application.sharpness import SharpnessService
from shotkeepr.core.domain.catalog.grouping import GroupingError
from shotkeepr.core.domain.catalog.ingestion import CatalogImportError, ExifToolUnavailableError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/photos", tags=["photos"], dependencies=[Depends(require_token)])
ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": ApiError},
    404: {"model": ApiError},
    409: {"model": ApiError},
    503: {"model": ApiError},
}


def _jobs(request: Request) -> ImportJobs:
    jobs: ImportJobs | None = request.app.state.import_jobs
    if jobs is None:
        raise HTTPException(503, "Importazione fotografica non configurata nel nucleo")
    return jobs


Jobs = Annotated[ImportJobs, Depends(_jobs)]


@router.post(
    "/imports",
    response_model=ImportJobOut,
    status_code=202,
    responses=ERRORS,
    operation_id="start_photo_import",
)
def start_photo_import(body: ImportRequest, jobs: Jobs) -> ImportJobOut:
    try:
        return jobs.start(Path(body.source_folder), recursive=body.include_subfolders)
    except ImportBusyError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ExifToolUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except CatalogImportError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get(
    "/imports/{job_id}",
    response_model=ImportJobOut,
    responses=ERRORS,
    operation_id="get_photo_import",
)
def get_photo_import(job_id: uuid.UUID, jobs: Jobs) -> ImportJobOut:
    try:
        return jobs.get(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Importazione non presente nel nucleo") from exc


@router.post(
    "/imports/{job_id}/cancel",
    response_model=ImportJobOut,
    responses=ERRORS,
    operation_id="cancel_photo_import",
)
def cancel_photo_import(job_id: uuid.UUID, jobs: Jobs) -> ImportJobOut:
    try:
        return jobs.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Importazione non presente nel nucleo") from exc


@router.get(
    "/sessions",
    response_model=list[SessionOut],
    responses=ERRORS,
    operation_id="list_photo_sessions",
)
def list_photo_sessions(jobs: Jobs) -> list[SessionOut]:
    return [
        SessionOut.from_domain(session, jobs.shots.count_by_session(session.session_id))
        for session in jobs.sessions.list()
    ]


@router.get(
    "/sessions/{session_id}",
    response_model=SessionOut,
    responses=ERRORS,
    operation_id="get_photo_session",
)
def get_photo_session(session_id: uuid.UUID, jobs: Jobs, request: Request) -> SessionOut:
    session = jobs.sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Sessione non presente nel catalogo")
    service: GroupingService | None = request.app.state.grouping_service
    try:
        grouping = None if service is None else service.get(session_id)
    except SQLAlchemyError as exc:
        logger.exception("Impossibile leggere i gruppi della sessione %s", session_id)
        raise HTTPException(503, "Lettura dei gruppi non riuscita") from exc
    except GroupingError as exc:
        raise HTTPException(409, str(exc)) from exc
    return SessionOut.from_domain(session, jobs.shots.count_by_session(session_id), grouping)


@router.get(
    "/sessions/{session_id}/shots",
    response_model=ShotPageOut,
    responses=ERRORS,
    operation_id="list_photo_shots",
)
def list_photo_shots(
    session_id: uuid.UUID,
    jobs: Jobs,
    request: Request,
    *,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    group_id: uuid.UUID | None = None,
    ungrouped: bool = False,
) -> ShotPageOut:
    if group_id is not None and ungrouped:
        raise HTTPException(400, "Filtro gruppo e senza gruppo non combinabili")
    session = get_photo_session(session_id, jobs, request)
    if group_id is not None:
        if session.grouping is None:
            raise HTTPException(503, "Raggruppamento fotografico non configurato nel nucleo")
        if not any(group.group_id == group_id for group in session.grouping.groups):
            raise HTTPException(404, "Gruppo non presente nella sessione")
    try:
        shots = jobs.shots.list_by_session(
            session_id, limit=limit, offset=offset, group_id=group_id, ungrouped=ungrouped
        )
        total = jobs.shots.count_by_session(session_id, group_id=group_id, ungrouped=ungrouped)
    except SQLAlchemyError as exc:
        logger.exception("Impossibile leggere gli scatti della sessione %s", session_id)
        raise HTTPException(503, "Lettura degli scatti non riuscita") from exc
    service: ExposureService | None = request.app.state.exposure_service
    try:
        measurements = (
            service.results.get_many([shot.shot_id for shot in shots])
            if service is not None
            else {}
        )
    except SQLAlchemyError as exc:
        logger.exception(
            "Impossibile leggere le misure di esposizione della sessione %s", session_id
        )
        raise HTTPException(503, "Lettura delle misure di esposizione non riuscita") from exc
    review_service: ReviewService | None = request.app.state.review_service
    try:
        reviews = (
            review_service.reviews.get_many([shot.shot_id for shot in shots])
            if review_service is not None
            else {}
        )
    except SQLAlchemyError as exc:
        logger.exception("Impossibile leggere le revisioni della sessione %s", session_id)
        raise HTTPException(503, "Lettura delle revisioni non riuscita") from exc
    sharpness_service: SharpnessService | None = request.app.state.sharpness_service
    try:
        sharpness = (
            sharpness_service.results.get_many([shot.shot_id for shot in shots])
            if sharpness_service is not None
            else {}
        )
    except SQLAlchemyError as exc:
        logger.exception("Impossibile leggere la nitidezza della sessione %s", session_id)
        raise HTTPException(503, "Lettura della nitidezza non riuscita") from exc
    return ShotPageOut(
        items=[
            ShotOut.from_domain(
                shot,
                measurements.get(shot.shot_id),
                reviews.get(shot.shot_id),
                sharpness.get(shot.shot_id),
            )
            for shot in shots
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/shots/{shot_id}/thumbnail",
    response_class=FileResponse,
    responses={
        **ERRORS,
        200: {"content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}}},
    },
    operation_id="get_photo_thumbnail",
)
def get_photo_thumbnail(shot_id: uuid.UUID, jobs: Jobs) -> FileResponse:
    shot = jobs.shots.get(shot_id)
    if shot is None or shot.preview_file is None:
        raise HTTPException(404, "Scatto non presente nel catalogo")
    file = shot.preview_file
    try:
        path = jobs.previews.path_for(file)
    except CatalogImportError as exc:
        raise HTTPException(409, "Percorso dell'anteprima non valido") from exc
    if not path.is_file():
        raise HTTPException(404, "Anteprima non presente nella cache")
    return FileResponse(path, media_type="image/jpeg")
