"""Rotte delle impostazioni applicazione (comp-016, if-021), protette da token."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from shotkeepr.core.api.auth import require_token
from shotkeepr.core.api.schemas import SettingsOut, SettingsPatch
from shotkeepr.core.application.configuration import ConfigurationService

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_token)])


def _service(request: Request) -> ConfigurationService:
    service: ConfigurationService = request.app.state.configuration_service
    return service


@router.get("", response_model=SettingsOut)
def get_settings(service: Annotated[ConfigurationService, Depends(_service)]) -> SettingsOut:
    return SettingsOut.from_domain(service.current())


@router.patch("", response_model=SettingsOut)
def patch_settings(
    patch: SettingsPatch, service: Annotated[ConfigurationService, Depends(_service)]
) -> SettingsOut:
    changes = patch.model_dump(exclude_none=True)
    updated = service.update(**changes) if changes else service.current()
    return SettingsOut.from_domain(updated)
