"""Persistenza locale (comp-017): SQLite WAL, SQLAlchemy 2, migrazioni Alembic (ADR-005)."""

from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.migrate import upgrade_to_head
from shotkeepr.core.adapters.persistence.repositories import (
    SqlSessionRepository,
    SqlShotRepository,
)
from shotkeepr.core.adapters.persistence.settings import SqlSettingsRepository

__all__ = [
    "Database",
    "SqlSessionRepository",
    "SqlSettingsRepository",
    "SqlShotRepository",
    "upgrade_to_head",
]
