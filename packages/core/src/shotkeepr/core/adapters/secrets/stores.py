"""Implementazioni della porta SecretStore."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

import keyring
import keyring.errors
from keyring.backends.fail import Keyring as FailKeyring

from shotkeepr.core.application.ports import SecretStore, SecretStoreUnavailableError

SERVICE = "shotkeepr"
ENV_PREFIX = "SHOTKEEPR_SECRET_"


class KeyringSecretStore:
    """Portachiavi del sistema operativo (Windows Credential Manager, Keychain, Secret Service)."""

    def __init__(self, service: str = SERVICE) -> None:
        self._service = service

    @staticmethod
    def available() -> bool:
        return not isinstance(keyring.get_keyring(), FailKeyring)

    def get(self, ref: str) -> str | None:
        try:
            return keyring.get_password(self._service, ref)
        except keyring.errors.KeyringError as exc:
            raise SecretStoreUnavailableError(str(exc)) from exc

    def set(self, ref: str, secret: str) -> None:
        try:
            keyring.set_password(self._service, ref, secret)
        except keyring.errors.KeyringError as exc:
            raise SecretStoreUnavailableError(str(exc)) from exc

    def delete(self, ref: str) -> None:
        try:
            keyring.delete_password(self._service, ref)
        except keyring.errors.PasswordDeleteError:
            return
        except keyring.errors.KeyringError as exc:
            raise SecretStoreUnavailableError(str(exc)) from exc


def env_name(ref: str) -> str:
    return ENV_PREFIX + re.sub(r"[^A-Z0-9]", "_", ref.upper())


class EnvSecretStore:
    """Sola lettura da variabili d'ambiente/Docker secrets, per il nucleo in container."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else os.environ

    def get(self, ref: str) -> str | None:
        return self._environ.get(env_name(ref))

    def set(self, ref: str, secret: str) -> None:
        raise SecretStoreUnavailableError(
            f"portachiavi non disponibile: impostare la variabile {env_name(ref)}"
        )

    def delete(self, ref: str) -> None:
        return


def default_secret_store() -> SecretStore:
    return KeyringSecretStore() if KeyringSecretStore.available() else EnvSecretStore()
