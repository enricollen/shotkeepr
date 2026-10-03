from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

T = TypeVar("T", bound="BurstGroupOut")


@_attrs_define
class BurstGroupOut:
    """
    Attributes:
        group_id (UUID):
        camera_model (str):
        camera_serial (str):
        shots (int):
        first_capture (datetime.datetime):
        last_capture (datetime.datetime):
    """

    group_id: UUID
    camera_model: str
    camera_serial: str
    shots: int
    first_capture: datetime.datetime
    last_capture: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        group_id = str(self.group_id)

        camera_model = self.camera_model

        camera_serial = self.camera_serial

        shots = self.shots

        first_capture = self.first_capture.isoformat()

        last_capture = self.last_capture.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "group_id": group_id,
                "camera_model": camera_model,
                "camera_serial": camera_serial,
                "shots": shots,
                "first_capture": first_capture,
                "last_capture": last_capture,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        group_id = UUID(d.pop("group_id"))

        camera_model = d.pop("camera_model")

        camera_serial = d.pop("camera_serial")

        shots = d.pop("shots")

        first_capture = datetime.datetime.fromisoformat(d.pop("first_capture"))

        last_capture = datetime.datetime.fromisoformat(d.pop("last_capture"))

        burst_group_out = cls(
            group_id=group_id,
            camera_model=camera_model,
            camera_serial=camera_serial,
            shots=shots,
            first_capture=first_capture,
            last_capture=last_capture,
        )

        burst_group_out.additional_properties = d
        return burst_group_out

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
