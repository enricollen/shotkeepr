"""Accesso alle credenziali (comp-016, ADR-009): portachiavi OS o variabili d'ambiente."""

from shotkeepr.core.adapters.secrets.stores import (
    EnvSecretStore,
    KeyringSecretStore,
    default_secret_store,
)

__all__ = ["EnvSecretStore", "KeyringSecretStore", "default_secret_store"]
