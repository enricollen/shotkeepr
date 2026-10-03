from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.burst_group_out import BurstGroupOut


T = TypeVar("T", bound="BurstGroupingOut")


@_attrs_define
class BurstGroupingOut:
    """
    Attributes:
        session_id (UUID):
        gap_seconds (float | None):
        method_version (None | str):
        grouped_at (datetime.datetime | None):
        groups (list[BurstGroupOut]):
        ungrouped_shots (int):
    """

    session_id: UUID
    gap_seconds: float | None
    method_version: None | str
    grouped_at: datetime.datetime | None
    groups: list[BurstGroupOut]
    ungrouped_shots: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        session_id = str(self.session_id)

        gap_seconds: float | None
        gap_seconds = self.gap_seconds

        method_version: None | str
        method_version = self.method_version

        grouped_at: None | str
        if isinstance(self.grouped_at, datetime.datetime):
            grouped_at = self.grouped_at.isoformat()
        else:
            grouped_at = self.grouped_at

        groups = []
        for groups_item_data in self.groups:
            groups_item = groups_item_data.to_dict()
            groups.append(groups_item)

        ungrouped_shots = self.ungrouped_shots

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "session_id": session_id,
                "gap_seconds": gap_seconds,
                "method_version": method_version,
                "grouped_at": grouped_at,
                "groups": groups,
                "ungrouped_shots": ungrouped_shots,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.burst_group_out import BurstGroupOut

        d = dict(src_dict)
        session_id = UUID(d.pop("session_id"))

        def _parse_gap_seconds(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        gap_seconds = _parse_gap_seconds(d.pop("gap_seconds"))

        def _parse_method_version(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        method_version = _parse_method_version(d.pop("method_version"))

        def _parse_grouped_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                grouped_at_type_0 = datetime.datetime.fromisoformat(data)

                return grouped_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        grouped_at = _parse_grouped_at(d.pop("grouped_at"))

        groups = []
        _groups = d.pop("groups")
        for groups_item_data in _groups:
            groups_item = BurstGroupOut.from_dict(groups_item_data)

            groups.append(groups_item)

        ungrouped_shots = d.pop("ungrouped_shots")

        burst_grouping_out = cls(
            session_id=session_id,
            gap_seconds=gap_seconds,
            method_version=method_version,
            grouped_at=grouped_at,
            groups=groups,
            ungrouped_shots=ungrouped_shots,
        )

        burst_grouping_out.additional_properties = d
        return burst_grouping_out

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
