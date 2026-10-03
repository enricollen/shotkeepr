"""Identita', provenienza, licenza e integrita' dei pesi ONNX."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from urllib.parse import urlsplit

CORE_LICENSES = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0"})
_IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{0,47}\Z")
_VERSION = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,47}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")


class Device(StrEnum):
    AUTO = "auto"
    CPU = "cpu"
    CUDA = "cuda"
    COREML = "coreml"


class ModelError(RuntimeError):
    """Errore operativo nel registro, nella cache o nel runtime AI."""


class InvalidModelManifestError(ValueError):
    """Manifest incompleto, non supportato o non sicuro."""


class ModelIntegrityError(ModelError):
    """Dimensione o SHA-256 dei pesi non corrispondenti al manifest."""


class ModelDownloadError(ModelError):
    """Download non riuscito; nessun artefatto parziale viene pubblicato."""


def validate_model_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port
    except ValueError as exc:
        raise InvalidModelManifestError("URL del modello non valido") from exc
    if (
        parsed.scheme != "https"
        or not host
        or "." not in host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or host.rstrip(".").endswith((".localhost", ".local", ".internal"))
    ):
        raise InvalidModelManifestError("i modelli richiedono URL HTTPS pubblici senza credenziali")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise InvalidModelManifestError(
            "un URL del modello non puo' puntare a un indirizzo privato"
        )
    if port is not None and port != 443:
        raise InvalidModelManifestError("gli URL dei modelli devono usare la porta HTTPS standard")


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    model_id: str
    version: str
    url: str
    sha256: str
    size_bytes: int
    license: str
    license_url: str
    source_url: str

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.model_id) or not _VERSION.fullmatch(self.version):
            raise InvalidModelManifestError("identificativo o versione del modello non validi")
        if not _SHA256.fullmatch(self.sha256):
            raise InvalidModelManifestError("sha256 deve contenere 64 cifre esadecimali minuscole")
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise InvalidModelManifestError("size_bytes deve essere un intero positivo")
        if self.license not in CORE_LICENSES:
            raise InvalidModelManifestError("licenza non approvata per i modelli del nucleo")
        for url in (self.url, self.license_url, self.source_url):
            validate_model_url(url)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ModelArtifact:
        text_fields = (
            "model_id",
            "version",
            "url",
            "sha256",
            "license",
            "license_url",
            "source_url",
        )
        if set(data) != {*text_fields, "size_bytes"}:
            raise InvalidModelManifestError("campi del modello mancanti o sconosciuti")
        values: dict[str, str] = {}
        for key in text_fields:
            value = data[key]
            if not isinstance(value, str):
                raise InvalidModelManifestError(f"{key} deve essere una stringa")
            values[key] = value
        size = data["size_bytes"]
        if not isinstance(size, int) or isinstance(size, bool):
            raise InvalidModelManifestError("size_bytes deve essere un intero positivo")
        return cls(size_bytes=size, **values)


@dataclass(frozen=True, slots=True)
class ModelManifest:
    models: tuple[ModelArtifact, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise InvalidModelManifestError("schema_version del manifest non supportata")
        keys = [(model.model_id, model.version) for model in self.models]
        if len(keys) != len(set(keys)):
            raise InvalidModelManifestError("versione duplicata nel manifest")

    def select(self, model_id: str, version: str | None = None) -> ModelArtifact:
        matches = [
            model
            for model in self.models
            if model.model_id == model_id and (version is None or model.version == version)
        ]
        if not matches:
            raise ModelError(f"modello non presente nel manifest: {model_id}")
        if len(matches) != 1:
            raise ModelError(f"specificare --version per il modello {model_id}")
        return matches[0]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "models": [model.to_dict() for model in self.models],
        }
