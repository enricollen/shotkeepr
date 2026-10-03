"""ExifTool merge on temporary sidecars; originals are only read for identity checks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from filelock import FileLock, Timeout

from shotkeepr.core.domain.catalog import ImageFile, Shot
from shotkeepr.core.domain.catalog.review import ReviewError, ShotReview, XmpUnavailableError

MAX_XMP_BYTES = 8 * 1024 * 1024


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


@dataclass(frozen=True, slots=True)
class _Snapshot:
    mode: int
    signature: tuple[int, ...]
    content: bytes


def _no_links(path: Path) -> None:
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(part.is_symlink() for part in (path, *path.parents))
    ):
        raise ReviewError(f"Percorso relativo o collegamento simbolico rifiutato: {path}")


def _target(file: ImageFile) -> Path:
    _no_links(file.path)
    target = file.path.with_suffix(".xmp")
    if target == file.path or file.path.suffix.casefold() == ".xmp":
        raise ReviewError("Il sidecar non puo' coincidere con un originale")
    existing = [
        item for item in target.parent.iterdir() if item.name.casefold() == target.name.casefold()
    ]
    if len(existing) > 1:
        raise ReviewError(f"Sidecar con maiuscole/minuscole ambigue: {target}")
    target = existing[0] if existing else target
    _no_links(target)
    return target


def _verify_original(file: ImageFile) -> tuple[int, ...]:
    _no_links(file.path)
    before = file.path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != file.size:
        raise ReviewError(f"Originale assente o modificato: {file.path}")
    with file.path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != file.fingerprint or _signature(before) != _signature(file.path.stat()):
        raise ReviewError(f"Originale modificato dopo l'importazione: {file.path}")
    return _signature(before)


def _snapshot(path: Path) -> _Snapshot | None:
    _no_links(path)
    if not path.exists():
        return None
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_XMP_BYTES:
        raise ReviewError(f"Sidecar non regolare o troppo grande: {path}")
    if not before.st_mode & 0o222:
        raise ReviewError(f"Sidecar in sola lettura: {path}")
    with path.open("rb") as stream:
        content = stream.read(MAX_XMP_BYTES + 1)
    if len(content) > MAX_XMP_BYTES or _signature(before) != _signature(path.stat()):
        raise ReviewError(f"Sidecar modificato durante la lettura: {path}")
    return _Snapshot(stat.S_IMODE(before.st_mode), _signature(before), content)


class ExifToolXmpWriter:
    def __init__(self, lock_dir: Path, *, executable: str = "exiftool") -> None:
        self._lock_dir, self._executable = lock_dir, executable

    def targets(self, shot: Shot) -> Sequence[Path]:
        if not shot.files:
            raise ReviewError("Lo scatto non contiene file immagine")
        try:
            return tuple(dict.fromkeys(_target(file) for file in shot.files))
        except OSError as exc:
            raise ReviewError(f"Cartella sorgente non accessibile: {exc}") from exc

    @staticmethod
    def _run(executable: str, args: Sequence[str]) -> str:
        try:
            result = subprocess.run(  # noqa: S603 -- resolved executable, no shell
                [executable, "-config", "", *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReviewError(
                "Export XMP scaduto; il sidecar corrente non e' stato sostituito"
            ) from exc
        if result.returncode or result.stderr.strip():
            raise ReviewError(f"ExifTool non ha completato il merge XMP: {result.stderr.strip()}")
        return result.stdout

    def _prepare(
        self,
        executable: str,
        target: Path,
        review: ShotReview,
        stack: ExitStack,
    ) -> tuple[Path, _Snapshot | None]:
        if not target.parent.stat().st_mode & 0o222:
            raise ReviewError(f"Cartella sorgente in sola lettura: {target.parent}")
        previous = _snapshot(target)
        directory = stack.enter_context(
            TemporaryDirectory(prefix=".shotkeepr-xmp-", dir=target.parent)
        )
        temporary = Path(directory) / "sidecar.xmp"
        tags = [f"-XMP-xmp:Rating={review.rating}", f"-XMP-xmp:Label={review.label}"]
        if previous is None:
            self._run(executable, [*tags, "-o", str(temporary)])
        else:
            temporary.write_bytes(previous.content)
            self._run(executable, ["-overwrite_original", *tags, "--", str(temporary)])
        output = self._run(
            executable,
            [
                "-json",
                "-n",
                "-FileType",
                "-XMP-xmp:Rating",
                "-XMP-xmp:Label",
                "-Error",
                "--",
                str(temporary),
            ],
        )
        try:
            records = json.loads(output)
        except json.JSONDecodeError as exc:
            raise ReviewError("Risposta di verifica XMP non valida") from exc
        if (
            not isinstance(records, list)
            or len(records) != 1
            or not isinstance(records[0], dict)
            or records[0].get("FileType") != "XMP"
            or records[0].get("Rating") != review.rating
            or records[0].get("Label") != review.label
            or "Error" in records[0]
        ):
            raise ReviewError("Il sidecar generato non contiene la revisione richiesta")
        if temporary.stat().st_size > MAX_XMP_BYTES:
            raise ReviewError("Il sidecar generato supera il limite di dimensione")
        mode = 0o600 if previous is None else previous.mode
        temporary.chmod(mode)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        return temporary, previous

    def write(self, shot: Shot, review: ShotReview) -> Sequence[Path]:
        executable = shutil.which(self._executable)
        if executable is None:
            raise XmpUnavailableError("ExifTool non disponibile: installarlo e aggiungerlo al PATH")
        published: list[Path] = []
        try:
            targets = self.targets(shot)
            self._lock_dir.mkdir(parents=True, exist_ok=True)
            with ExitStack() as stack:
                for target in sorted(targets):
                    key = hashlib.sha256(str(target).casefold().encode("utf-8")).hexdigest()
                    stack.enter_context(FileLock(self._lock_dir / f"{key}.lock", timeout=0))
                verified = [(file, _verify_original(file)) for file in shot.files]
                prepared = [
                    (target, *self._prepare(executable, target, review, stack))
                    for target in targets
                ]
                for file, signature in verified:
                    _no_links(file.path)
                    if _signature(file.path.stat()) != signature:
                        raise ReviewError(f"Originale modificato durante l'export: {file.path}")
                if tuple(self.targets(shot)) != tuple(targets):
                    raise ReviewError("Percorsi sidecar modificati durante l'export")
                for target, _temporary, previous in prepared:
                    if _snapshot(target) != previous:
                        raise ReviewError(f"Sidecar modificato da un altro programma: {target}")
                for target, temporary, previous in prepared:
                    if previous is None:
                        # A newly appeared sidecar must never be overwritten.
                        os.link(temporary, target)
                    else:
                        temporary.replace(target)
                    published.append(target)
        except (OSError, ReviewError, Timeout) as exc:
            completed = ", ".join(str(path) for path in published) or "nessuno"
            raise ReviewError(
                f"Export XMP non completato: {exc}; sidecar pubblicati: {completed}"
            ) from exc
        return published
