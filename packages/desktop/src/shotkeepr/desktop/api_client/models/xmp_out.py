from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.review_status import ReviewStatus

T = TypeVar("T", bound="XmpOut")


@_attrs_define
class XmpOut:
    """
    Attributes:
        shot_id (UUID):
        status (ReviewStatus):
        paths (list[str]):
    """

    shot_id: UUID
    status: ReviewStatus
    paths: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        shot_id = str(self.shot_id)

        status = self.status.value

        paths = self.paths

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "shot_id": shot_id,
                "status": status,
                "paths": paths,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        shot_id = UUID(d.pop("shot_id"))

        status = ReviewStatus(d.pop("status"))

        paths = cast(list[str], d.pop("paths"))

        xmp_out = cls(
            shot_id=shot_id,
            status=status,
            paths=paths,
        )

        xmp_out.additional_properties = d
        return xmp_out

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
