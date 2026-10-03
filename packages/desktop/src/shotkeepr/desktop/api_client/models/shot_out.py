from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.exposure_out import ExposureOut
    from ..models.photo_file_out import PhotoFileOut
    from ..models.review_out import ReviewOut
    from ..models.sharpness_out import SharpnessOut


T = TypeVar("T", bound="ShotOut")


@_attrs_define
class ShotOut:
    """
    Attributes:
        shot_id (UUID):
        capture_time (datetime.datetime | None):
        is_raw_pair (bool):
        files (list[PhotoFileOut]):
        exposure (ExposureOut | None | Unset):
        review (None | ReviewOut | Unset):
        group_id (None | Unset | UUID):
        sharpness (None | SharpnessOut | Unset):
    """

    shot_id: UUID
    capture_time: datetime.datetime | None
    is_raw_pair: bool
    files: list[PhotoFileOut]
    exposure: ExposureOut | None | Unset = UNSET
    review: None | ReviewOut | Unset = UNSET
    group_id: None | Unset | UUID = UNSET
    sharpness: None | SharpnessOut | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.exposure_out import ExposureOut
        from ..models.review_out import ReviewOut
        from ..models.sharpness_out import SharpnessOut

        shot_id = str(self.shot_id)

        capture_time: None | str
        if isinstance(self.capture_time, datetime.datetime):
            capture_time = self.capture_time.isoformat()
        else:
            capture_time = self.capture_time

        is_raw_pair = self.is_raw_pair

        files = []
        for files_item_data in self.files:
            files_item = files_item_data.to_dict()
            files.append(files_item)

        exposure: dict[str, Any] | None | Unset
        if isinstance(self.exposure, Unset):
            exposure = UNSET
        elif isinstance(self.exposure, ExposureOut):
            exposure = self.exposure.to_dict()
        else:
            exposure = self.exposure

        review: dict[str, Any] | None | Unset
        if isinstance(self.review, Unset):
            review = UNSET
        elif isinstance(self.review, ReviewOut):
            review = self.review.to_dict()
        else:
            review = self.review

        group_id: None | str | Unset
        if isinstance(self.group_id, Unset):
            group_id = UNSET
        elif isinstance(self.group_id, UUID):
            group_id = str(self.group_id)
        else:
            group_id = self.group_id

        sharpness: dict[str, Any] | None | Unset
        if isinstance(self.sharpness, Unset):
            sharpness = UNSET
        elif isinstance(self.sharpness, SharpnessOut):
            sharpness = self.sharpness.to_dict()
        else:
            sharpness = self.sharpness

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "shot_id": shot_id,
                "capture_time": capture_time,
                "is_raw_pair": is_raw_pair,
                "files": files,
            }
        )
        if exposure is not UNSET:
            field_dict["exposure"] = exposure
        if review is not UNSET:
            field_dict["review"] = review
        if group_id is not UNSET:
            field_dict["group_id"] = group_id
        if sharpness is not UNSET:
            field_dict["sharpness"] = sharpness

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.exposure_out import ExposureOut
        from ..models.photo_file_out import PhotoFileOut
        from ..models.review_out import ReviewOut
        from ..models.sharpness_out import SharpnessOut

        d = dict(src_dict)
        shot_id = UUID(d.pop("shot_id"))

        def _parse_capture_time(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                capture_time_type_0 = datetime.datetime.fromisoformat(data)

                return capture_time_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        capture_time = _parse_capture_time(d.pop("capture_time"))

        is_raw_pair = d.pop("is_raw_pair")

        files = []
        _files = d.pop("files")
        for files_item_data in _files:
            files_item = PhotoFileOut.from_dict(files_item_data)

            files.append(files_item)

        def _parse_exposure(data: object) -> ExposureOut | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                exposure_type_0 = ExposureOut.from_dict(data)

                return exposure_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ExposureOut | None | Unset, data)

        exposure = _parse_exposure(d.pop("exposure", UNSET))

        def _parse_review(data: object) -> None | ReviewOut | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                review_type_0 = ReviewOut.from_dict(data)

                return review_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | ReviewOut | Unset, data)

        review = _parse_review(d.pop("review", UNSET))

        def _parse_group_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                group_id_type_0 = UUID(data)

                return group_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        group_id = _parse_group_id(d.pop("group_id", UNSET))

        def _parse_sharpness(data: object) -> None | SharpnessOut | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                sharpness_type_0 = SharpnessOut.from_dict(data)

                return sharpness_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | SharpnessOut | Unset, data)

        sharpness = _parse_sharpness(d.pop("sharpness", UNSET))

        shot_out = cls(
            shot_id=shot_id,
            capture_time=capture_time,
            is_raw_pair=is_raw_pair,
            files=files,
            exposure=exposure,
            review=review,
            group_id=group_id,
            sharpness=sharpness,
        )

        shot_out.additional_properties = d
        return shot_out

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
