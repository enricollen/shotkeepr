import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image

from shotkeepr.core.adapters.ingestion.previews import PillowRawPreviewStore
from shotkeepr.core.adapters.persistence.db import Database
from shotkeepr.core.adapters.persistence.exposure import SqlExposureRepository
from shotkeepr.core.adapters.persistence.migrate import upgrade_to_head
from shotkeepr.core.adapters.persistence.repositories import SqlSessionRepository, SqlShotRepository
from shotkeepr.core.adapters.quality.exposure import PillowExposureAnalyzer
from shotkeepr.core.application.exposure import ExposureService
from shotkeepr.core.domain.catalog import FileKind, ImageFile, Session, SessionStatus, Shot
from shotkeepr.core.domain.quality.exposure import ExposureMetrics


class CountingAnalyzer(PillowExposureAnalyzer):
    def __init__(self) -> None:
        self.calls = 0

    def measure(self, content: bytes) -> ExposureMetrics:
        self.calls += 1
        return super().measure(content)


@dataclass
class ExposureCatalog:
    db: Database
    data: Path
    session: Session
    shot: Shot
    preview: Path
    previews: PillowRawPreviewStore
    sessions: SqlSessionRepository
    shots: SqlShotRepository
    results: SqlExposureRepository
    analyzer: CountingAnalyzer
    service: ExposureService


@pytest.fixture
def catalog(tmp_path: Path) -> Iterator[ExposureCatalog]:
    folder = tmp_path / "originals"
    folder.mkdir()
    source = folder / "photo.jpg"
    with Image.new("RGB", (64, 32), (128, 128, 128)) as image:
        image.save(source)
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    file = ImageFile(source, "JPEG", FileKind.STANDARD, len(content), digest)
    data = tmp_path / "data"
    db = Database.at(data / "shotkeepr.db")
    upgrade_to_head(db.url)
    sessions, shots = SqlSessionRepository(db), SqlShotRepository(db)
    session = Session(folder, status=SessionStatus.IMPORTED, checkpoint=1)
    shot = Shot(session.session_id, digest, files=[file])
    sessions.add(session)
    shots.add_many([shot])
    previews = PillowRawPreviewStore(data / "previews")
    preview = previews.create(file)
    results = SqlExposureRepository(db)
    analyzer = CountingAnalyzer()
    service = ExposureService(shots, previews, results, analyzer)
    try:
        yield ExposureCatalog(
            db, data, session, shot, preview, previews, sessions, shots, results, analyzer, service
        )
    finally:
        db.dispose()
