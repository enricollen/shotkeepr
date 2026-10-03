"""Authenticated temporal grouping, distinct from AI analysis and review."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.api.auth import require_token
from shotkeepr.core.api.photo_schemas import BurstGroupingOut, BurstRequest
from shotkeepr.core.api.routes.photos import ERRORS
from shotkeepr.core.application.grouping import GroupingService
from shotkeepr.core.domain.catalog.grouping import GroupingError, GroupingSessionNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/photos", tags=["photos"], dependencies=[Depends(require_token)])


def _service(request: Request) -> GroupingService:
    service: GroupingService | None = request.app.state.grouping_service
    if service is None:
        raise HTTPException(503, "Raggruppamento fotografico non configurato nel nucleo")
    return service


Service = Annotated[GroupingService, Depends(_service)]


def _error(exc: GroupingError | SQLAlchemyError) -> HTTPException:
    if isinstance(exc, SQLAlchemyError):
        logger.exception("Lettura o salvataggio del raggruppamento non riuscito")
        return HTTPException(503, "Catalogo non disponibile per il raggruppamento")
    if isinstance(exc, GroupingSessionNotFoundError):
        return HTTPException(404, str(exc))
    return HTTPException(409, str(exc))


@router.get(
    "/sessions/{session_id}/groups",
    response_model=BurstGroupingOut,
    responses=ERRORS,
    operation_id="get_photo_groups",
)
def get_photo_groups(session_id: uuid.UUID, service: Service) -> BurstGroupingOut:
    try:
        return BurstGroupingOut.from_domain(service.get(session_id))
    except (GroupingError, SQLAlchemyError) as exc:
        raise _error(exc) from exc


@router.post(
    "/sessions/{session_id}/groups/bursts",
    response_model=BurstGroupingOut,
    responses=ERRORS,
    operation_id="group_photo_bursts",
)
def group_photo_bursts(
    session_id: uuid.UUID, body: BurstRequest, service: Service
) -> BurstGroupingOut:
    try:
        return BurstGroupingOut.from_domain(service.regroup(session_id, body.gap_seconds))
    except (GroupingError, SQLAlchemyError) as exc:
        raise _error(exc) from exc
