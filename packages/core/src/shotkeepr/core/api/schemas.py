"""Schemi Pydantic del contratto `/api/v1` (if-002, if-003)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from shotkeepr.core import __version__
from shotkeepr.core.domain.configuration import AppSettings, LogLevel, Theme


class HealthOut(BaseModel):
    status: str = "ok"
    version: str = __version__


class LlmProviderOut(BaseModel):
    provider: str
    model: str
    endpoint: str | None = None
    send_image: bool = False
    timeout_s: float = 10.0


class SettingsOut(BaseModel):
    theme: str
    catalog_enabled: bool
    edition: str
    log_level: str
    llm: LlmProviderOut | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, settings: AppSettings) -> SettingsOut:
        llm = (
            LlmProviderOut(
                provider=settings.llm.provider,
                model=settings.llm.model,
                endpoint=settings.llm.endpoint,
                send_image=settings.llm.send_image,
                timeout_s=settings.llm.timeout_s,
            )
            if settings.llm
            else None
        )
        return cls(
            theme=settings.theme.value,
            catalog_enabled=settings.catalog_enabled,
            edition=settings.edition.value,
            log_level=settings.log_level.value,
            llm=llm,
            extra=dict(settings.extra),
        )


class SettingsPatch(BaseModel):
    """Campi opzionali: solo quelli presenti vengono aggiornati."""

    theme: Theme | None = None
    catalog_enabled: bool | None = None
    log_level: LogLevel | None = None
