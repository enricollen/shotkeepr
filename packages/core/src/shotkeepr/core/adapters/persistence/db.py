"""Engine SQLite in modalità WAL e fabbrica di sessioni transazionali."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker


def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


class Database:
    """Punto di accesso unico al database locale."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: Engine = create_engine(url, future=True)
        event.listen(self.engine, "connect", _set_pragmas)
        self._factory = sessionmaker(self.engine, expire_on_commit=False)

    @classmethod
    def at(cls, path: Path) -> Database:
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls(sqlite_url(path))

    @contextmanager
    def transaction(self) -> Iterator[OrmSession]:
        with self._factory.begin() as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()
