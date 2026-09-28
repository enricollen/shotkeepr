"""Casi d'uso di configurazione (comp-016, if-021)."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from shotkeepr.core.application.ports import SecretStore, SettingsRepository
from shotkeepr.core.domain.configuration import AppSettings, Edition, LlmProviderConfig

EDITION_ENV = "SHOTKEEPR_EDITION"


class ConfigurationService:
    def __init__(self, settings: SettingsRepository, secrets: SecretStore) -> None:
        self._settings = settings
        self._secrets = secrets

    def current(self) -> AppSettings:
        stored = self._settings.load() or AppSettings()
        forced = os.environ.get(EDITION_ENV)
        return stored.with_changes(edition=Edition(forced)) if forced else stored

    def update(self, **changes: Any) -> AppSettings:
        updated = self.current().with_changes(**changes)
        self._settings.save(updated)
        return updated

    def configure_llm(self, config: LlmProviderConfig, api_key: str | None = None) -> AppSettings:
        """Salva il provider; la chiave va solo nel portachiavi, mai nelle impostazioni."""
        if api_key:
            ref = config.credential_ref or f"llm.{config.provider}"
            self._secrets.set(ref, api_key)
            config = replace(config, credential_ref=ref)
        return self.update(llm=config)

    def remove_llm(self) -> AppSettings:
        current = self.current()
        if current.llm and current.llm.credential_ref:
            self._secrets.delete(current.llm.credential_ref)
        return self.update(llm=None)

    def llm_api_key(self) -> str | None:
        llm = self.current().llm
        if llm is None or llm.credential_ref is None:
            return None
        return self._secrets.get(llm.credential_ref)
