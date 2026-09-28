from __future__ import annotations

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends.fail import Keyring as FailKeyring
from keyring.errors import PasswordDeleteError

from shotkeepr.core.adapters.secrets import (
    EnvSecretStore,
    KeyringSecretStore,
    default_secret_store,
)
from shotkeepr.core.adapters.secrets.stores import env_name
from shotkeepr.core.application.ports import SecretStoreUnavailableError


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.data.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.data[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.data:
            raise PasswordDeleteError(username)
        del self.data[(service, username)]


@pytest.fixture
def memory_keyring() -> MemoryKeyring:
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend  # type: ignore[misc]
    keyring.set_keyring(previous)


def test_keyring_store(memory_keyring: MemoryKeyring) -> None:
    store = KeyringSecretStore()
    assert KeyringSecretStore.available()
    store.set("llm.openai", "sk-1")
    assert memory_keyring.data == {("shotkeepr", "llm.openai"): "sk-1"}
    assert store.get("llm.openai") == "sk-1"
    store.delete("llm.openai")
    store.delete("llm.openai")
    assert store.get("llm.openai") is None
    assert isinstance(default_secret_store(), KeyringSecretStore)


def test_fail_keyring_falls_back_to_env() -> None:
    previous = keyring.get_keyring()
    keyring.set_keyring(FailKeyring())
    try:
        assert not KeyringSecretStore.available()
        assert isinstance(default_secret_store(), EnvSecretStore)
        with pytest.raises(SecretStoreUnavailableError):
            KeyringSecretStore().get("x")
        with pytest.raises(SecretStoreUnavailableError):
            KeyringSecretStore().set("x", "y")
        with pytest.raises(SecretStoreUnavailableError):
            KeyringSecretStore().delete("x")
    finally:
        keyring.set_keyring(previous)


def test_env_store() -> None:
    store = EnvSecretStore({"SHOTKEEPR_SECRET_LLM_OPENAI": "sk-env"})
    assert env_name("llm.openai") == "SHOTKEEPR_SECRET_LLM_OPENAI"
    assert store.get("llm.openai") == "sk-env"
    assert store.get("other") is None
    store.delete("llm.openai")
    with pytest.raises(SecretStoreUnavailableError, match="SHOTKEEPR_SECRET_X"):
        store.set("x", "y")
