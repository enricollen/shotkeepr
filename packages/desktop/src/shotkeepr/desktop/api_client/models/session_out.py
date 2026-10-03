from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.session_status import SessionStatus
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.burst_grouping_out import BurstGroupingOut
    from ..models.excluded_file_out import ExcludedFileOut


T = TypeVar("T", bound="SessionOut")


@_attrs_define
class SessionOut:
    """
    Attributes:
        session_id (UUID):
        source_folder (str):
        include_subfolders (bool):
        status (SessionStatus):
        processed (int):
        shots (int):
        started_at (datetime.datetime):
        excluded (list[ExcludedFileOut]):
        grouping (BurstGroupingOut | None | Unset):
    """

    session_id: UUID
    source_folder: str
    include_subfolders: bool
    status: SessionStatus
    processed: int
    shots: int
    started_at: datetime.datetime
    excluded: list[ExcludedFileOut]
    grouping: BurstGroupingOut | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.burst_grouping_out import BurstGroupingOut

        session_id = str(self.session_id)

        source_folder = self.source_folder

        include_subfolders = self.include_subfolders

        status = self.status.value

        processed = self.processed

        shots = self.shots

        started_at = self.started_at.isoformat()

        excluded = []
        for excluded_item_data in self.excluded:
            excluded_item = excluded_item_data.to_dict()
            excluded.append(excluded_item)

        grouping: dict[str, Any] | None | Unset
        if isinstance(self.grouping, Unset):
            grouping = UNSET
        elif isinstance(self.grouping, BurstGroupingOut):
            grouping = self.grouping.to_dict()
        else:
            grouping = self.grouping

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "session_id": session_id,
                "source_folder": source_folder,
                "include_subfolders": include_subfolders,
                "status": status,
                "processed": processed,
                "shots": shots,
                "started_at": started_at,
                "excluded": excluded,
            }
        )
        if grouping is not UNSET:
            field_dict["grouping"] = grouping

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.burst_grouping_out import BurstGroupingOut
        from ..models.excluded_file_out import ExcludedFileOut

        d = dict(src_dict)
        session_id = UUID(d.pop("session_id"))

        source_folder = d.pop("source_folder")

        include_subfolders = d.pop("include_subfolders")

        status = SessionStatus(d.pop("status"))

        processed = d.pop("processed")

        shots = d.pop("shots")

        started_at = datetime.datetime.fromisoformat(d.pop("started_at"))

        excluded = []
        _excluded = d.pop("excluded")
        for excluded_item_data in _excluded:
            excluded_item = ExcludedFileOut.from_dict(excluded_item_data)

            excluded.append(excluded_item)

        def _parse_grouping(data: object) -> BurstGroupingOut | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                grouping_type_0 = BurstGroupingOut.from_dict(data)

                return grouping_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(BurstGroupingOut | None | Unset, data)

        grouping = _parse_grouping(d.pop("grouping", UNSET))

        session_out = cls(
            session_id=session_id,
            source_folder=source_folder,
            include_subfolders=include_subfolders,
            status=status,
            processed=processed,
            shots=shots,
            started_at=started_at,
            excluded=excluded,
            grouping=grouping,
        )

        session_out.additional_properties = d
        return session_out

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
