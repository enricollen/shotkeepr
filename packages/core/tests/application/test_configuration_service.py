from __future__ import annotations

from pathlib import Path

import pytest

from shotkeepr.core.adapters.persistence import Database, SqlSettingsRepository, upgrade_to_head
from shotkeepr.core.application.configuration import EDITION_ENV, ConfigurationService
from shotkeepr.core.domain.configuration import Edition, LlmProviderConfig, Theme


class MemorySecrets:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, ref: str) -> str | None:
        return self.data.get(ref)

    def set(self, ref: str, secret: str) -> None:
        self.data[ref] = secret

    def delete(self, ref: str) -> None:
        self.data.pop(ref, None)


@pytest.fixture
def service(tmp_path: Path) -> tuple[ConfigurationService, MemorySecrets, Database]:
    db = Database.at(tmp_path / "s.db")
    upgrade_to_head(db.url)
    secrets = MemorySecrets()
    return ConfigurationService(SqlSettingsRepository(db), secrets), secrets, db


def test_update_persists(service: tuple[ConfigurationService, MemorySecrets, Database]) -> None:
    svc, _, db = service
    svc.update(theme=Theme.LIGHT)
    assert ConfigurationService(SqlSettingsRepository(db), MemorySecrets()).current().theme is (
        Theme.LIGHT
    )
    svc.update(catalog_enabled=True)
    assert svc.current().theme is Theme.LIGHT
    assert svc.current().catalog_enabled


def test_llm_key_goes_only_to_secret_store(
    service: tuple[ConfigurationService, MemorySecrets, Database],
) -> None:
    svc, secrets, db = service
    settings = svc.configure_llm(LlmProviderConfig("openai", "gpt-4o-mini"), api_key="sk-abc12345")
    assert settings.llm is not None
    assert settings.llm.credential_ref == "llm.openai"
    assert secrets.data == {"llm.openai": "sk-abc12345"}
    assert svc.llm_api_key() == "sk-abc12345"
    with db.engine.connect() as conn:
        dump = "\n".join(conn.connection.iterdump())  # type: ignore[attr-defined]
    assert "sk-abc12345" not in dump

    svc.remove_llm()
    assert secrets.data == {}
    assert svc.current().llm is None
    assert svc.llm_api_key() is None


def test_llm_without_key(service: tuple[ConfigurationService, MemorySecrets, Database]) -> None:
    svc, secrets, _ = service
    svc.configure_llm(LlmProviderConfig("ollama", "llama3"))
    assert svc.llm_api_key() is None
    svc.remove_llm()
    assert secrets.data == {}


def test_edition_forced_by_env(
    service: tuple[ConfigurationService, MemorySecrets, Database], monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, _, _ = service
    monkeypatch.setenv(EDITION_ENV, "COMMERCIAL")
    assert svc.current().edition is Edition.COMMERCIAL
