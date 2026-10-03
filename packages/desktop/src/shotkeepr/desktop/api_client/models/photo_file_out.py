from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.file_kind import FileKind

if TYPE_CHECKING:
    from ..models.metadata_out import MetadataOut


T = TypeVar("T", bound="PhotoFileOut")


@_attrs_define
class PhotoFileOut:
    """
    Attributes:
        file_id (UUID):
        path (str):
        format_ (str):
        kind (FileKind):
        size_bytes (int):
        metadata (MetadataOut):
    """

    file_id: UUID
    path: str
    format_: str
    kind: FileKind
    size_bytes: int
    metadata: MetadataOut
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        file_id = str(self.file_id)

        path = self.path

        format_ = self.format_

        kind = self.kind.value

        size_bytes = self.size_bytes

        metadata = self.metadata.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "file_id": file_id,
                "path": path,
                "format": format_,
                "kind": kind,
                "size_bytes": size_bytes,
                "metadata": metadata,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.metadata_out import MetadataOut

        d = dict(src_dict)
        file_id = UUID(d.pop("file_id"))

        path = d.pop("path")

        format_ = d.pop("format")

        kind = FileKind(d.pop("kind"))

        size_bytes = d.pop("size_bytes")

        metadata = MetadataOut.from_dict(d.pop("metadata"))

        photo_file_out = cls(
            file_id=file_id,
            path=path,
            format_=format_,
            kind=kind,
            size_bytes=size_bytes,
            metadata=metadata,
        )

        photo_file_out.additional_properties = d
        return photo_file_out

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
