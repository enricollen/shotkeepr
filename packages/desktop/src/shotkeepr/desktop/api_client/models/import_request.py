from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="ImportRequest")


@_attrs_define
class ImportRequest:
    """
    Attributes:
        source_folder (str):
        include_subfolders (bool | Unset):  Default: True.
    """

    source_folder: str
    include_subfolders: bool | Unset = True
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        source_folder = self.source_folder

        include_subfolders = self.include_subfolders

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "source_folder": source_folder,
            }
        )
        if include_subfolders is not UNSET:
            field_dict["include_subfolders"] = include_subfolders

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        source_folder = d.pop("source_folder")

        include_subfolders = d.pop("include_subfolders", UNSET)

        import_request = cls(
            source_folder=source_folder,
            include_subfolders=include_subfolders,
        )

        import_request.additional_properties = d
        return import_request

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
