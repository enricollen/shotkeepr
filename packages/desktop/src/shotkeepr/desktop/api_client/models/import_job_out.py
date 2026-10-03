from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.import_job_status import ImportJobStatus

T = TypeVar("T", bound="ImportJobOut")


@_attrs_define
class ImportJobOut:
    """
    Attributes:
        job_id (UUID):
        session_id (UUID):
        source_folder (str):
        status (ImportJobStatus):
        processed (int):  Default: 0.
        imported_files (int):  Default: 0.
        excluded_files (int):  Default: 0.
        shots (int):  Default: 0.
        current_file (None | str):
        error (None | str):
        cancel_requested (bool):  Default: False.
    """

    job_id: UUID
    session_id: UUID
    source_folder: str
    status: ImportJobStatus
    current_file: None | str
    error: None | str
    processed: int = 0
    imported_files: int = 0
    excluded_files: int = 0
    shots: int = 0
    cancel_requested: bool = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        job_id = str(self.job_id)

        session_id = str(self.session_id)

        source_folder = self.source_folder

        status = self.status.value

        processed = self.processed

        imported_files = self.imported_files

        excluded_files = self.excluded_files

        shots = self.shots

        current_file: None | str
        current_file = self.current_file

        error: None | str
        error = self.error

        cancel_requested = self.cancel_requested

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "job_id": job_id,
                "session_id": session_id,
                "source_folder": source_folder,
                "status": status,
                "processed": processed,
                "imported_files": imported_files,
                "excluded_files": excluded_files,
                "shots": shots,
                "current_file": current_file,
                "error": error,
                "cancel_requested": cancel_requested,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        job_id = UUID(d.pop("job_id"))

        session_id = UUID(d.pop("session_id"))

        source_folder = d.pop("source_folder")

        status = ImportJobStatus(d.pop("status"))

        processed = d.pop("processed")

        imported_files = d.pop("imported_files")

        excluded_files = d.pop("excluded_files")

        shots = d.pop("shots")

        def _parse_current_file(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        current_file = _parse_current_file(d.pop("current_file"))

        def _parse_error(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        error = _parse_error(d.pop("error"))

        cancel_requested = d.pop("cancel_requested")

        import_job_out = cls(
            job_id=job_id,
            session_id=session_id,
            source_folder=source_folder,
            status=status,
            processed=processed,
            imported_files=imported_files,
            excluded_files=excluded_files,
            shots=shots,
            current_file=current_file,
            error=error,
            cancel_requested=cancel_requested,
        )

        import_job_out.additional_properties = d
        return import_job_out

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
