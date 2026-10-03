"""Fabbrica dell'applicazione FastAPI `/api/v1` (comp-002, ADR-003)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from shotkeepr.core import __version__
from shotkeepr.core.api.events import EventBus
from shotkeepr.core.api.import_jobs import ImportJobs
from shotkeepr.core.api.routes import (
    events,
    exposure,
    grouping,
    health,
    photos,
    review,
    settings,
    sharpness,
)
from shotkeepr.core.application.configuration import ConfigurationService
from shotkeepr.core.application.exposure import ExposureService
from shotkeepr.core.application.grouping import GroupingService
from shotkeepr.core.application.review import ReviewService
from shotkeepr.core.application.sharpness import SharpnessService

API_PREFIX = "/api/v1"


def create_app(
    configuration_service: ConfigurationService,
    api_token: str,
    *,
    event_bus: EventBus | None = None,
    import_jobs: ImportJobs | None = None,
    exposure_service: ExposureService | None = None,
    review_service: ReviewService | None = None,
    grouping_service: GroupingService | None = None,
    sharpness_service: SharpnessService | None = None,
) -> FastAPI:
    """Crea l'app con stato iniettato: token locale, servizio di configurazione, bus eventi."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if import_jobs is not None:
                await asyncio.to_thread(import_jobs.shutdown)

    app = FastAPI(title="ShotKeepr core API", version=__version__, lifespan=lifespan)
    app.state.api_token = api_token
    app.state.configuration_service = configuration_service
    app.state.event_bus = event_bus or EventBus()
    app.state.import_jobs = import_jobs
    app.state.exposure_service = exposure_service
    app.state.review_service = review_service
    app.state.grouping_service = grouping_service
    app.state.sharpness_service = sharpness_service
    if import_jobs is not None:
        import_jobs.events = app.state.event_bus

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(settings.router, prefix=API_PREFIX)
    app.include_router(events.router, prefix=API_PREFIX)
    app.include_router(photos.router, prefix=API_PREFIX)
    app.include_router(exposure.router, prefix=API_PREFIX)
    app.include_router(review.router, prefix=API_PREFIX)
    app.include_router(grouping.router, prefix=API_PREFIX)
    app.include_router(sharpness.router, prefix=API_PREFIX)
    return app
