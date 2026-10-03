"""Authenticated manual review and explicitly confirmed XMP writes."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.api.auth import require_token
from shotkeepr.core.api.photo_schemas import ReviewOut, ReviewRequest, XmpOut, XmpRequest
from shotkeepr.core.api.routes.photos import ERRORS
from shotkeepr.core.application.review import ReviewService
from shotkeepr.core.domain.catalog.review import (
    ReviewError,
    ReviewShotNotFoundError,
    XmpUnavailableError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/photos", tags=["photos"], dependencies=[Depends(require_token)])


def _service(request: Request) -> ReviewService:
    service: ReviewService | None = request.app.state.review_service
    if service is None:
        raise HTTPException(503, "Revisioni fotografiche non configurate nel nucleo")
    return service


Service = Annotated[ReviewService, Depends(_service)]


def _error(exc: ReviewError | SQLAlchemyError) -> HTTPException:
    if isinstance(exc, SQLAlchemyError):
        logger.exception("Accesso alle revisioni fotografiche non riuscito")
        return HTTPException(503, "Lettura o salvataggio della revisione non riuscito")
    if isinstance(exc, ReviewShotNotFoundError):
        return HTTPException(404, str(exc))
    if isinstance(exc, XmpUnavailableError):
        return HTTPException(503, str(exc))
    return HTTPException(409, str(exc))


@router.get(
    "/shots/{shot_id}/review",
    response_model=ReviewOut,
    responses=ERRORS,
    operation_id="get_photo_review",
)
def get_photo_review(shot_id: uuid.UUID, service: Service) -> ReviewOut:
    try:
        return ReviewOut.from_domain(service.get(shot_id))
    except (ReviewError, SQLAlchemyError) as exc:
        raise _error(exc) from exc


@router.put(
    "/shots/{shot_id}/review",
    response_model=ReviewOut,
    responses=ERRORS,
    operation_id="set_photo_review",
)
def set_photo_review(shot_id: uuid.UUID, body: ReviewRequest, service: Service) -> ReviewOut:
    try:
        return ReviewOut.from_domain(service.set_status(shot_id, body.status))
    except (ReviewError, SQLAlchemyError) as exc:
        raise _error(exc) from exc


@router.post(
    "/shots/{shot_id}/xmp",
    response_model=XmpOut,
    responses=ERRORS,
    operation_id="export_photo_xmp",
)
def export_photo_xmp(shot_id: uuid.UUID, body: XmpRequest, service: Service) -> XmpOut:
    try:
        paths = service.export(shot_id, body.expected_status)
        return XmpOut(
            shot_id=shot_id, status=body.expected_status, paths=[str(path) for path in paths]
        )
    except (ReviewError, SQLAlchemyError) as exc:
        raise _error(exc) from exc
