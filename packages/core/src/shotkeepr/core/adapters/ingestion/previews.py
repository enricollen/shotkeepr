"""Anteprime orientate e miniature versionate: nessuna scrittura sugli originali."""

from __future__ import annotations

import hashlib
import io
import tempfile
from pathlib import Path

import pillow_heif
import rawpy
from PIL import Image, ImageOps, UnidentifiedImageError

from shotkeepr.core.domain.catalog import ExclusionReason, FileKind, ImageFile
from shotkeepr.core.domain.catalog.ingestion import CatalogImportError, FileInspectionError

PREVIEW_SIZE = 512
CACHE_VERSION = "v1-512"
pillow_heif.register_heif_opener()


class PillowRawPreviewStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def validate_destination(self, source: Path) -> None:
        if self.root.is_relative_to(source.resolve()):
            raise CatalogImportError(
                "la cache delle anteprime deve essere esterna alla cartella sorgente"
            )

    def path_for(self, file: ImageFile) -> Path:
        if len(file.fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in file.fingerprint
        ):
            raise CatalogImportError("impronta del file non valida per la cache")
        path = self.root / CACHE_VERSION / file.fingerprint[:2] / f"{file.fingerprint}.jpg"
        if not path.resolve().is_relative_to(self.root) or path.is_symlink():
            raise CatalogImportError("percorso della cache delle anteprime non sicuro")
        return path

    @staticmethod
    def _standard(path: Path) -> Image.Image:
        try:
            with Image.open(path) as image:
                image.draft("RGB", (PREVIEW_SIZE, PREVIEW_SIZE))
                image.load()
                return ImageOps.exif_transpose(image).convert("RGB")
        except (FileNotFoundError, PermissionError) as exc:
            raise FileInspectionError(
                ExclusionReason.UNREADABLE, "file immagine non accessibile"
            ) from exc
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
            raise FileInspectionError(
                ExclusionReason.CORRUPTED, "decodifica immagine non riuscita"
            ) from exc

    @staticmethod
    def _raw(path: Path) -> Image.Image:
        try:
            with rawpy.imread(str(path)) as raw:
                # JPEG incorporato se presente; altrimenti RAW a meta' risoluzione.
                try:
                    thumbnail = raw.extract_thumb()
                except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
                    thumbnail = None
                if thumbnail is not None and thumbnail.format == rawpy.ThumbFormat.JPEG:
                    with Image.open(io.BytesIO(thumbnail.data)) as image:
                        image.load()
                        if image.getexif().get(274) is not None:
                            return ImageOps.exif_transpose(image).convert("RGB")
                        rotation = {
                            3: Image.Transpose.ROTATE_180,
                            5: Image.Transpose.ROTATE_90,
                            6: Image.Transpose.ROTATE_270,
                        }.get(raw.sizes.flip)
                        oriented = (
                            image.transpose(rotation) if rotation is not None else image.copy()
                        )
                        with oriented:
                            return oriented.convert("RGB")
                pixels = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
                return Image.fromarray(pixels).convert("RGB")
        except (
            rawpy.LibRawError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
            OSError,
            ValueError,
        ) as exc:
            raise FileInspectionError(
                ExclusionReason.CORRUPTED, "decodifica RAW non riuscita"
            ) from exc

    def create(self, file: ImageFile) -> Path:
        destination = self.path_for(file)
        if destination.exists():
            try:
                with Image.open(destination) as cached:
                    if cached.format != "JPEG" or max(cached.size) > PREVIEW_SIZE:
                        raise CatalogImportError(
                            "formato o dimensione dell'anteprima in cache non validi"
                        )
                    cached.load()
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                raise CatalogImportError(
                    "anteprima in cache corrotta: rimuoverla prima di riprovare"
                ) from exc
            return destination
        image = self._raw(file.path) if file.kind is FileKind.RAW else self._standard(file.path)
        with image:
            try:
                with file.path.open("rb") as source:
                    actual = hashlib.file_digest(source, "sha256").hexdigest()
                if actual != file.fingerprint:
                    raise FileInspectionError(
                        ExclusionReason.UNREADABLE, "file modificato durante la decodifica"
                    )
            except OSError as exc:
                raise FileInspectionError(ExclusionReason.UNREADABLE, str(exc)) from exc
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, suffix=".part", delete=False
            ) as output:
                temporary = Path(output.name)
            try:
                image.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.Resampling.LANCZOS)
                image.save(temporary, format="JPEG", quality=85)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
        return destination
