from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.exclusion_reason import ExclusionReason

T = TypeVar("T", bound="ExcludedFileOut")


@_attrs_define
class ExcludedFileOut:
    """
    Attributes:
        path (str):
        reason (ExclusionReason):
        detail (str):
    """

    path: str
    reason: ExclusionReason
    detail: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        path = self.path

        reason = self.reason.value

        detail = self.detail

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "path": path,
                "reason": reason,
                "detail": detail,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        path = d.pop("path")

        reason = ExclusionReason(d.pop("reason"))

        detail = d.pop("detail")

        excluded_file_out = cls(
            path=path,
            reason=reason,
            detail=detail,
        )

        excluded_file_out.additional_properties = d
        return excluded_file_out

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
