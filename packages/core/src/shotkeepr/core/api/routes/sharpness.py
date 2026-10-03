"""Explicit cached-preview detail measurements, not subject focus or AI scoring."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.api.auth import require_token
from shotkeepr.core.api.photo_schemas import SharpnessOut
from shotkeepr.core.api.routes.photos import ERRORS
from shotkeepr.core.application.sharpness import SharpnessService
from shotkeepr.core.domain.quality.sharpness import SharpnessError, SharpnessShotNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/photos", tags=["photos"], dependencies=[Depends(require_token)])


def _service(request: Request) -> SharpnessService:
    service: SharpnessService | None = request.app.state.sharpness_service
    if service is None:
        raise HTTPException(503, "Misura della nitidezza non configurata nel nucleo")
    return service


Service = Annotated[SharpnessService, Depends(_service)]


@router.post(
    "/shots/{shot_id}/sharpness",
    response_model=SharpnessOut,
    responses=ERRORS,
    operation_id="measure_photo_sharpness",
)
def measure_photo_sharpness(shot_id: uuid.UUID, service: Service) -> SharpnessOut:
    try:
        return SharpnessOut.from_domain(service.measure(shot_id))
    except SharpnessShotNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except SharpnessError as exc:
        raise HTTPException(409, str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.exception("Impossibile salvare la misura di nitidezza dello scatto %s", shot_id)
        raise HTTPException(503, "Salvataggio della nitidezza non riuscito") from exc


@router.get(
    "/shots/{shot_id}/sharpness",
    response_model=SharpnessOut,
    responses=ERRORS,
    operation_id="get_photo_sharpness",
)
def get_photo_sharpness(shot_id: uuid.UUID, service: Service) -> SharpnessOut:
    try:
        if service.shots.get(shot_id) is None:
            raise HTTPException(404, "Scatto non presente nel catalogo")
        saved = service.results.get(shot_id)
        if saved is None:
            raise HTTPException(404, "Nitidezza non ancora misurata")
        return SharpnessOut.from_domain(saved)
    except SQLAlchemyError as exc:
        logger.exception("Impossibile leggere la nitidezza dello scatto %s", shot_id)
        raise HTTPException(503, "Lettura della nitidezza non riuscita") from exc
