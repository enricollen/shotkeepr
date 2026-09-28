"""Repository delle impostazioni applicazione."""

from __future__ import annotations

from datetime import UTC, datetime

from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.models import AppSettingsRow
from shotkeepr.core.domain.configuration import AppSettings

_ROW_ID = 1


class SqlSettingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def load(self) -> AppSettings | None:
        with self._db.transaction() as tx:
            row = tx.get(AppSettingsRow, _ROW_ID)
            return None if row is None else AppSettings.from_dict(row.data)

    def save(self, settings: AppSettings) -> None:
        now = datetime.now(UTC)
        with self._db.transaction() as tx:
            row = tx.get(AppSettingsRow, _ROW_ID)
            if row is None:
                tx.add(AppSettingsRow(id=_ROW_ID, data=settings.to_dict(), updated_at=now))
            else:
                row.data = settings.to_dict()
                row.updated_at = now
