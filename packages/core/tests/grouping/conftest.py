import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shotkeepr.core.domain.catalog import FileKind, ImageFile, Shot, ShotMetadata

from ..quality.conftest import catalog as catalog  # noqa: PLC0414 -- shared persisted catalog


def shot(
    session_id: uuid.UUID,
    seconds: float,
    *,
    model: str | None = "Test camera",
    serial: str | None = "CAM-1",
    folder: Path = Path("/photos"),
) -> Shot:
    captured = datetime(2026, 10, 3, tzinfo=UTC) + timedelta(seconds=seconds)
    name = str(uuid.uuid4())
    metadata = ShotMetadata(camera_model=model, camera_serial=serial, capture_time=captured)
    file = ImageFile(folder / f"{name}.jpg", "JPEG", FileKind.STANDARD, 10, "a" * 64, metadata)
    return Shot(session_id, name, capture_time=captured, files=[file])
