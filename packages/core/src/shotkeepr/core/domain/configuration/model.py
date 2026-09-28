"""Impostazioni applicazione (ent-029) e configurazione del provider LLM (ent-030)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

_CREDENTIAL_REF = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class InvalidConfigurationError(ValueError):
    """Valore di configurazione non ammesso."""


class Theme(StrEnum):
    LIGHT = "LIGHT"
    DARK = "DARK"


class Edition(StrEnum):
    OPEN = "OPEN"
    COMMERCIAL = "COMMERCIAL"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class LlmProviderConfig:
    """Provider e modello per le spiegazioni discorsive; la chiave resta nel portachiavi."""

    provider: str
    model: str
    endpoint: str | None = None
    credential_ref: str | None = None
    send_image: bool = False
    timeout_s: float = 10.0

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise InvalidConfigurationError("provider e modello sono obbligatori")
        if self.endpoint is not None:
            parsed = urlparse(self.endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise InvalidConfigurationError(f"endpoint non valido: {self.endpoint!r}")
        if self.credential_ref is not None and not _CREDENTIAL_REF.match(self.credential_ref):
            raise InvalidConfigurationError("credential_ref deve essere un identificativo")
        if not 1.0 <= self.timeout_s <= 120.0:
            raise InvalidConfigurationError("timeout_s deve essere tra 1 e 120 secondi")

    @property
    def litellm_model(self) -> str:
        return f"{self.provider}/{self.model}"


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Preferenze locali dell'utente e dell'edizione."""

    theme: Theme = Theme.DARK
    catalog_enabled: bool = False
    edition: Edition = Edition.OPEN
    log_level: LogLevel = LogLevel.INFO
    llm: LlmProviderConfig | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def allows_non_commercial_plugins(self) -> bool:
        return self.edition is Edition.OPEN

    def with_changes(self, **changes: Any) -> AppSettings:
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["theme"] = self.theme.value
        data["edition"] = self.edition.value
        data["log_level"] = self.log_level.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        try:
            llm = data.get("llm")
            return cls(
                theme=Theme(data.get("theme", Theme.DARK)),
                catalog_enabled=bool(data.get("catalog_enabled", False)),
                edition=Edition(data.get("edition", Edition.OPEN)),
                log_level=LogLevel(data.get("log_level", LogLevel.INFO)),
                llm=LlmProviderConfig(**llm) if llm else None,
                extra=dict(data.get("extra", {})),
            )
        except (TypeError, ValueError) as exc:
            raise InvalidConfigurationError(str(exc)) from exc
