"""Misure parziali su anteprima: esplicite, autenticate e non equivalenti ad analisi AI."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from shotkeepr.core.api.auth import require_token
from shotkeepr.core.api.photo_schemas import ExposureOut
from shotkeepr.core.api.routes.photos import ERRORS
from shotkeepr.core.application.exposure import ExposureService
from shotkeepr.core.domain.quality.exposure import ExposureError, ExposureShotNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/photos", tags=["photos"], dependencies=[Depends(require_token)])


def _service(request: Request) -> ExposureService:
    service: ExposureService | None = request.app.state.exposure_service
    if service is None:
        raise HTTPException(503, "Misura dell'esposizione non configurata nel nucleo")
    return service


Service = Annotated[ExposureService, Depends(_service)]


@router.post(
    "/shots/{shot_id}/exposure",
    response_model=ExposureOut,
    responses=ERRORS,
    operation_id="measure_photo_exposure",
)
def measure_photo_exposure(shot_id: uuid.UUID, service: Service) -> ExposureOut:
    try:
        return ExposureOut.from_domain(service.measure(shot_id))
    except ExposureShotNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ExposureError as exc:
        raise HTTPException(409, str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.exception("Impossibile salvare la misura di esposizione dello scatto %s", shot_id)
        raise HTTPException(503, "Salvataggio della misura non riuscito") from exc


@router.get(
    "/shots/{shot_id}/exposure",
    response_model=ExposureOut,
    responses=ERRORS,
    operation_id="get_photo_exposure",
)
def get_photo_exposure(shot_id: uuid.UUID, service: Service) -> ExposureOut:
    try:
        if service.shots.get(shot_id) is None:
            raise HTTPException(404, "Scatto non presente nel catalogo")
        result = service.results.get(shot_id)
        if result is None:
            raise HTTPException(404, "Esposizione non ancora misurata")
        return ExposureOut.from_domain(result)
    except SQLAlchemyError as exc:
        logger.exception("Impossibile leggere la misura di esposizione dello scatto %s", shot_id)
        raise HTTPException(503, "Lettura della misura non riuscita") from exc
