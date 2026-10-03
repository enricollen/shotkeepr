from collections.abc import Iterator
from pathlib import Path

import pytest

from shotkeepr.core.adapters.ingestion.previews import PillowRawPreviewStore
from shotkeepr.core.adapters.ingestion.source import ExifToolPhotoSource
from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.migrate import upgrade_to_head
from shotkeepr.core.adapters.persistence.repositories import (
    SqlCatalogWriter,
    SqlSessionRepository,
    SqlShotRepository,
)
from shotkeepr.core.application.ingestion import PhotoImportService
from shotkeepr.core.domain.catalog import (
    ExcludedFile,
    ExclusionReason,
    ImageFile,
    Session,
    SessionStatus,
    Shot,
)
from shotkeepr.core.domain.catalog.ingestion import CatalogImportError


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database.at(tmp_path / "data" / "shotkeepr.db")
    upgrade_to_head(database.url)
    try:
        yield database
    finally:
        database.dispose()


def test_import_persists_shots_metadata_exclusions_and_does_not_analyze(
    exiftool: str,
    photograph: ImageFile,
    db: Database,
    tmp_path: Path,
) -> None:
    folder = photograph.path.parent
    (folder / "notes.txt").write_text("notes", encoding="utf-8")
    (folder / "broken.jpg").write_bytes(b"\xff\xd8\xfftruncated")
    originals = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in folder.iterdir()}
    sessions = SqlSessionRepository(db)
    service = PhotoImportService(
        ExifToolPhotoSource(executable=exiftool),
        PillowRawPreviewStore(tmp_path / "cache"),
        sessions,
        SqlCatalogWriter(db),
    )
    progress = []
    result = service.import_folder(folder, progress=progress.append)
    assert result.session.status == SessionStatus.IMPORTED
    assert result.session.checkpoint == 3
    assert len(result.shots) == 1
    assert len(result.session.excluded) == 2
    assert progress[-1].processed == 3
    assert progress[-1].imported == 1
    assert progress[-1].excluded == 2
    assert sessions.get(result.session.session_id) == result.session
    loaded = SqlShotRepository(db).list_by_session(result.session.session_id)
    assert loaded == list(result.shots)
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in folder.iterdir()
    } == originals


def test_service_failure_leaves_failed_session_without_partial_shots(
    exiftool: str,
    photograph: ImageFile,
    db: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = ExifToolPhotoSource(executable=exiftool)
    sessions = SqlSessionRepository(db)

    def unavailable(path: Path) -> ImageFile:
        raise CatalogImportError("metadata service unavailable")

    monkeypatch.setattr(source, "inspect", unavailable)
    service = PhotoImportService(
        source, PillowRawPreviewStore(tmp_path / "cache"), sessions, SqlCatalogWriter(db)
    )
    with pytest.raises(CatalogImportError, match="unavailable"):
        service.import_folder(photograph.path.parent)
    saved = sessions.list()
    assert len(saved) == 1
    assert saved[0].status == SessionStatus.FAILED
    assert SqlShotRepository(db).list_by_session(saved[0].session_id) == []


def test_catalog_write_failure_is_atomic(db: Database) -> None:
    session = Session(Path("/photos"), status=SessionStatus.IMPORTING)
    sessions = SqlSessionRepository(db)
    sessions.add(session)
    session.status = SessionStatus.IMPORTED
    first = Shot(session.session_id, "same-hash")
    second = Shot(session.session_id, "same-hash")
    with pytest.raises(CatalogImportError, match="salvataggio"):
        SqlCatalogWriter(db).save_import(session, [first, second])
    assert sessions.get(session.session_id).status == SessionStatus.IMPORTING
    assert SqlShotRepository(db).list_by_session(session.session_id) == []


def test_empty_folder_import_is_explicitly_not_analyzed(
    exiftool: str, db: Database, tmp_path: Path
) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()
    service = PhotoImportService(
        ExifToolPhotoSource(executable=exiftool),
        PillowRawPreviewStore(tmp_path / "cache"),
        SqlSessionRepository(db),
        SqlCatalogWriter(db),
    )
    result = service.import_folder(folder)
    assert result.session.status == SessionStatus.IMPORTED
    assert result.shots == ()
    assert result.session.checkpoint == 0


def test_source_containing_cache_is_rejected_before_session_creation(
    exiftool: str,
    photograph: ImageFile,
    db: Database,
) -> None:
    sessions = SqlSessionRepository(db)
    service = PhotoImportService(
        ExifToolPhotoSource(executable=exiftool),
        PillowRawPreviewStore(photograph.path.parent / "cache"),
        sessions,
        SqlCatalogWriter(db),
    )
    with pytest.raises(CatalogImportError, match="esterna"):
        service.import_folder(photograph.path.parent)
    assert sessions.list() == []


def test_catalog_failure_marks_session_failed_without_publishing(
    exiftool: str,
    photograph: ImageFile,
    db: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = SqlSessionRepository(db)
    writer = SqlCatalogWriter(db)

    def fail(session: Session, shots: list[Shot]) -> None:
        raise CatalogImportError("catalog write failed")

    monkeypatch.setattr(writer, "save_import", fail)
    service = PhotoImportService(
        ExifToolPhotoSource(executable=exiftool),
        PillowRawPreviewStore(tmp_path / "cache"),
        sessions,
        writer,
    )
    with pytest.raises(CatalogImportError, match="write failed"):
        service.import_folder(photograph.path.parent)
    saved = sessions.list()[0]
    assert saved.status == SessionStatus.FAILED
    assert saved.checkpoint == 1
    assert SqlShotRepository(db).list_by_session(saved.session_id) == []


def test_scan_exclusions_are_persisted_without_inspection(
    exiftool: str,
    db: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()
    source = ExifToolPhotoSource(executable=exiftool)
    excluded = ExcludedFile(folder / "unreadable", ExclusionReason.UNREADABLE, "permission denied")
    monkeypatch.setattr(source, "scan", lambda root, recursive: iter([excluded]))
    service = PhotoImportService(
        source,
        PillowRawPreviewStore(tmp_path / "cache"),
        SqlSessionRepository(db),
        SqlCatalogWriter(db),
    )
    result = service.import_folder(folder)
    assert result.session.excluded == [excluded]
    assert result.session.checkpoint == 1
    assert result.shots == ()


def test_library_rejects_database_inside_source_before_creating_a_session(
    exiftool: str,
    photograph: ImageFile,
    tmp_path: Path,
) -> None:
    database = Database.at(photograph.path.parent / "catalog.db")
    try:
        upgrade_to_head(database.url)
        sessions = SqlSessionRepository(database)
        service = PhotoImportService(
            ExifToolPhotoSource(executable=exiftool),
            PillowRawPreviewStore(tmp_path / "cache"),
            sessions,
            SqlCatalogWriter(database),
        )
        with pytest.raises(CatalogImportError, match=r"database.*esterno"):
            service.import_folder(photograph.path.parent)
        assert sessions.list() == []
    finally:
        database.dispose()
