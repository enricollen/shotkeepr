from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from shotkeepr.core.adapters.persistence import (
    Database,
    SqlSessionRepository,
    SqlShotRepository,
    upgrade_to_head,
)
from shotkeepr.core.adapters.persistence.migrate import downgrade_to_base
from shotkeepr.core.adapters.persistence.models import Base
from shotkeepr.core.domain.catalog import (
    ExcludedFile,
    ExclusionReason,
    FileKind,
    ImageFile,
    Session,
    SessionStatus,
    Shot,
    ShotMetadata,
)

EXPECTED_TABLES = {
    "sessions",
    "excluded_files",
    "shots",
    "image_files",
    "analysis_results",
    "subjects",
    "shot_groups",
    "group_corrections",
    "profiles",
    "selection_runs",
    "decisions",
    "manual_status_changes",
}


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database.at(tmp_path / "data" / "shotkeepr.db")
    upgrade_to_head(database.url)
    return database


def _shot(session: Session, name: str, ts: datetime) -> Shot:
    meta = ShotMetadata(camera_model="X-T5", camera_serial="123", iso=400, capture_time=ts)
    return Shot(
        session_id=session.session_id,
        content_hash=f"hash-{name}",
        capture_time=ts,
        files=[
            ImageFile(Path(f"/p/{name}.RAF"), "RAF", FileKind.RAW, 10, "fp1", meta),
            ImageFile(Path(f"/p/{name}.JPG"), "JPEG", FileKind.STANDARD, 5, "fp2", meta),
        ],
    )


def test_migration_creates_schema_and_wal(db: Database) -> None:
    tables = set(inspect(db.engine).get_table_names())
    assert tables >= EXPECTED_TABLES
    with db.engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_migration_matches_models(db: Database) -> None:
    with db.engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_downgrade_removes_everything(db: Database) -> None:
    downgrade_to_base(db.url)
    assert set(inspect(db.engine).get_table_names()) <= {"alembic_version"}


def test_session_roundtrip(db: Database) -> None:
    repo = SqlSessionRepository(db)
    s = Session(
        source_folder=Path("/photos/wedding"),
        excluded=[ExcludedFile(Path("/photos/wedding/a.txt"), ExclusionReason.UNSUPPORTED)],
    )
    repo.add(s)
    loaded = repo.get(s.session_id)
    assert loaded == s
    assert loaded.started_at.tzinfo is not None

    s.status = SessionStatus.ANALYZING
    s.checkpoint = 42
    s.excluded = []
    repo.update(s)
    assert repo.get(s.session_id) == s
    assert [x.session_id for x in repo.list()] == [s.session_id]
    assert repo.get(uuid.uuid4()) is None


def test_update_missing_session_raises(db: Database) -> None:
    with pytest.raises(KeyError):
        SqlSessionRepository(db).update(Session(source_folder=Path("/x")))


def test_shot_roundtrip_and_hash_lookup(db: Database) -> None:
    sessions, shots = SqlSessionRepository(db), SqlShotRepository(db)
    s = Session(source_folder=Path("/p"))
    sessions.add(s)
    t1, t2 = datetime(2026, 5, 1, 10, 0, 1, tzinfo=UTC), datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)
    a, b = _shot(s, "a", t1), _shot(s, "b", t2)
    shots.add_many([a, b])

    listed = shots.list_by_session(s.session_id)
    assert [x.shot_id for x in listed] == [b.shot_id, a.shot_id]
    got = shots.get(a.shot_id)
    assert got is not None
    assert got.is_raw_pair
    assert {f.path for f in got.files} == {f.path for f in a.files}
    assert got.files[0].metadata.capture_time == t1
    assert shots.find_by_hash(s.session_id, "hash-b") is not None
    assert shots.find_by_hash(s.session_id, "missing") is None
    assert shots.get(uuid.uuid4()) is None


def test_duplicate_hash_in_session_rejected(db: Database) -> None:
    sessions, shots = SqlSessionRepository(db), SqlShotRepository(db)
    s = Session(source_folder=Path("/p"))
    sessions.add(s)
    ts = datetime(2026, 5, 1, tzinfo=UTC)
    shots.add_many([_shot(s, "a", ts)])
    with pytest.raises(IntegrityError):
        shots.add_many([_shot(s, "a", ts)])


def test_naive_datetime_rejected(db: Database) -> None:
    s = Session(source_folder=Path("/p"), started_at=datetime(2026, 1, 1))
    with pytest.raises(Exception, match="fuso"):
        SqlSessionRepository(db).add(s)
