from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

T = TypeVar("T", bound="ExposureOut")


@_attrs_define
class ExposureOut:
    """
    Attributes:
        shot_id (UUID):
        source_fingerprint (str):
        preview_sha256 (str):
        analyzer_version (str):
        measured_at (datetime.datetime):
        width (int):
        height (int):
        mean_luma (float):
        highlights_fraction (float):
        shadows_fraction (float):
        score (float):
    """

    shot_id: UUID
    source_fingerprint: str
    preview_sha256: str
    analyzer_version: str
    measured_at: datetime.datetime
    width: int
    height: int
    mean_luma: float
    highlights_fraction: float
    shadows_fraction: float
    score: float
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        shot_id = str(self.shot_id)

        source_fingerprint = self.source_fingerprint

        preview_sha256 = self.preview_sha256

        analyzer_version = self.analyzer_version

        measured_at = self.measured_at.isoformat()

        width = self.width

        height = self.height

        mean_luma = self.mean_luma

        highlights_fraction = self.highlights_fraction

        shadows_fraction = self.shadows_fraction

        score = self.score

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "shot_id": shot_id,
                "source_fingerprint": source_fingerprint,
                "preview_sha256": preview_sha256,
                "analyzer_version": analyzer_version,
                "measured_at": measured_at,
                "width": width,
                "height": height,
                "mean_luma": mean_luma,
                "highlights_fraction": highlights_fraction,
                "shadows_fraction": shadows_fraction,
                "score": score,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        shot_id = UUID(d.pop("shot_id"))

        source_fingerprint = d.pop("source_fingerprint")

        preview_sha256 = d.pop("preview_sha256")

        analyzer_version = d.pop("analyzer_version")

        measured_at = datetime.datetime.fromisoformat(d.pop("measured_at"))

        width = d.pop("width")

        height = d.pop("height")

        mean_luma = d.pop("mean_luma")

        highlights_fraction = d.pop("highlights_fraction")

        shadows_fraction = d.pop("shadows_fraction")

        score = d.pop("score")

        exposure_out = cls(
            shot_id=shot_id,
            source_fingerprint=source_fingerprint,
            preview_sha256=preview_sha256,
            analyzer_version=analyzer_version,
            measured_at=measured_at,
            width=width,
            height=height,
            mean_luma=mean_luma,
            highlights_fraction=highlights_fraction,
            shadows_fraction=shadows_fraction,
            score=score,
        )

        exposure_out.additional_properties = d
        return exposure_out

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
