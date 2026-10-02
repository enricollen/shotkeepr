"""Fabbrica dell'applicazione FastAPI `/api/v1` (comp-002, ADR-003)."""

from __future__ import annotations

from fastapi import FastAPI

from shotkeepr.core import __version__
from shotkeepr.core.api.events import EventBus
from shotkeepr.core.api.routes import events, health, settings
from shotkeepr.core.application.configuration import ConfigurationService

API_PREFIX = "/api/v1"


def create_app(
    configuration_service: ConfigurationService,
    api_token: str,
    *,
    event_bus: EventBus | None = None,
) -> FastAPI:
    """Crea l'app con stato iniettato: token locale, servizio di configurazione, bus eventi."""
    app = FastAPI(title="ShotKeepr core API", version=__version__)
    app.state.api_token = api_token
    app.state.configuration_service = configuration_service
    app.state.event_bus = event_bus or EventBus()

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(settings.router, prefix=API_PREFIX)
    app.include_router(events.router, prefix=API_PREFIX)
    return app
