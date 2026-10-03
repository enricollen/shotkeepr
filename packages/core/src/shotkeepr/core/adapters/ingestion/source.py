"""Scansione senza symlink e riconoscimento per contenuto tramite ExifTool."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path

from shotkeepr.core.domain.catalog import (
    ExcludedFile,
    ExclusionReason,
    FileKind,
    ImageFile,
    ShotMetadata,
)
from shotkeepr.core.domain.catalog.ingestion import (
    CatalogImportError,
    ExifToolUnavailableError,
    FileInspectionError,
)

RAW_FORMATS = frozenset({"ARW", "CR2", "CR3", "NEF", "ORF", "RAF", "RW2", "PEF", "DNG"})
STANDARD_FORMATS = {
    "JPEG": "JPEG",
    "PNG": "PNG",
    "TIFF": "TIFF",
    "HEIC": "HEIC",
    "HEIF": "HEIC",
    "WEBP": "WEBP",
}
IMAGE_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".webp"}
) | frozenset(f".{name.lower()}" for name in RAW_FORMATS)
_TAGS = (
    "FileType",
    "Error",
    "Model",
    "SerialNumber",
    "BodySerialNumber",
    "LensModel",
    "FocalLength",
    "ExposureTime",
    "FNumber",
    "ISO",
    "SubSecDateTimeOriginal",
    "DateTimeOriginal",
    "SubSecTimeOriginal",
    "OffsetTimeOriginal",
)


def _text(data: Mapping[str, object], name: str) -> str | None:
    value = data.get(name)
    return str(value).strip() if isinstance(value, (str, int)) and str(value).strip() else None


def _number(data: Mapping[str, object], name: str) -> float | None:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) and result > 0 else None


def _capture_time(data: Mapping[str, object]) -> datetime | None:
    combined = _text(data, "SubSecDateTimeOriginal")
    timestamp = combined or _text(data, "DateTimeOriginal")
    if timestamp is None:
        return None
    if not combined:
        fractional = _text(data, "SubSecTimeOriginal")
        if fractional is not None and fractional.isdigit():
            timestamp += f".{fractional}"
        offset = _text(data, "OffsetTimeOriginal")
        if offset is not None:
            timestamp += offset
    normalized = timestamp[:10].replace(":", "-") + timestamp[10:]
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    # In assenza di offset, UTC e' la convenzione di archiviazione dell'ora locale camera.
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def metadata_from_tags(data: Mapping[str, object]) -> ShotMetadata:
    iso = _number(data, "ISO")
    return ShotMetadata(
        camera_model=_text(data, "Model"),
        camera_serial=_text(data, "SerialNumber") or _text(data, "BodySerialNumber"),
        lens=_text(data, "LensModel"),
        focal_mm=_number(data, "FocalLength"),
        exposure_s=_number(data, "ExposureTime"),
        aperture=_number(data, "FNumber"),
        iso=int(iso) if iso is not None else None,
        capture_time=_capture_time(data),
    )


class ExifToolPhotoSource:
    def __init__(self, *, executable: str = "exiftool") -> None:
        located = shutil.which(executable)
        if located is None:
            raise ExifToolUnavailableError(
                "ExifTool non disponibile: installarlo e aggiungerlo al PATH"
            )
        self._executable = located

    def validate_folder(self, folder: Path) -> Path:
        root = folder.resolve(strict=True)
        if not root.is_dir():
            raise CatalogImportError("la sorgente deve essere una cartella")
        # Verifica i permessi prima di creare una sessione persistente.
        next(root.iterdir(), None)
        return root

    def scan(self, folder: Path, *, recursive: bool) -> Iterator[Path | ExcludedFile]:
        pending = [folder]
        while pending:
            directory = pending.pop()
            try:
                entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
            except OSError as exc:
                yield ExcludedFile(directory, ExclusionReason.UNREADABLE, str(exc))
                continue
            for entry in entries:
                if entry.is_symlink():
                    yield ExcludedFile(
                        entry, ExclusionReason.UNREADABLE, "collegamento simbolico non seguito"
                    )
                elif entry.is_dir():
                    if recursive:
                        pending.append(entry)
                elif entry.is_file():
                    yield entry
                else:
                    yield ExcludedFile(
                        entry, ExclusionReason.UNREADABLE, "file non regolare o non accessibile"
                    )

    def _tags(self, path: Path) -> dict[str, object]:
        try:
            result = subprocess.run(  # noqa: S603 -- eseguibile risolto e argomenti senza shell
                [self._executable, "-json", "-n", *(f"-{tag}" for tag in _TAGS), "--", str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CatalogImportError("ExifTool non e' piu' disponibile") from exc
        except subprocess.TimeoutExpired as exc:
            raise FileInspectionError(
                ExclusionReason.UNREADABLE, "lettura dei metadati scaduta"
            ) from exc
        except OSError as exc:
            raise CatalogImportError("avvio di ExifTool non riuscito") from exc
        try:
            records = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise CatalogImportError("risposta JSON di ExifTool non valida") from exc
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise CatalogImportError("ExifTool non ha restituito i metadati richiesti")
        data: dict[str, object] = records[0]
        error = _text(data, "Error")
        if error is not None:
            reason = (
                ExclusionReason.CORRUPTED
                if path.suffix.lower() in IMAGE_SUFFIXES
                else ExclusionReason.UNSUPPORTED
            )
            raise FileInspectionError(reason, error)
        if result.returncode != 0:
            raise FileInspectionError(
                ExclusionReason.UNREADABLE, "ExifTool non ha completato la lettura"
            )
        return data

    def inspect(self, path: Path) -> ImageFile:
        if path.is_symlink():
            raise FileInspectionError(
                ExclusionReason.UNREADABLE, "collegamento simbolico non seguito"
            )
        try:
            before = path.stat()
            data = self._tags(path)
            file_type = (_text(data, "FileType") or "").upper()
            if file_type in RAW_FORMATS:
                kind, image_format = FileKind.RAW, file_type
            elif file_type in STANDARD_FORMATS:
                kind, image_format = FileKind.STANDARD, STANDARD_FORMATS[file_type]
            else:
                raise FileInspectionError(
                    ExclusionReason.UNSUPPORTED,
                    f"formato non supportato: {file_type or 'sconosciuto'}",
                )
            with path.open("rb") as source:
                fingerprint = hashlib.file_digest(source, "sha256").hexdigest()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ino,
            ):
                raise FileInspectionError(
                    ExclusionReason.UNREADABLE, "file modificato durante l'importazione"
                )
            return ImageFile(
                path, image_format, kind, after.st_size, fingerprint, metadata_from_tags(data)
            )
        except OSError as exc:
            raise FileInspectionError(ExclusionReason.UNREADABLE, str(exc)) from exc
