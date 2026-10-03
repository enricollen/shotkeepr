from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

T = TypeVar("T", bound="MetadataOut")


@_attrs_define
class MetadataOut:
    """
    Attributes:
        camera_model (None | str):
        camera_serial (None | str):
        lens (None | str):
        focal_mm (float | None):
        exposure_s (float | None):
        aperture (float | None):
        iso (int | None):
        capture_time (datetime.datetime | None):
    """

    camera_model: None | str
    camera_serial: None | str
    lens: None | str
    focal_mm: float | None
    exposure_s: float | None
    aperture: float | None
    iso: int | None
    capture_time: datetime.datetime | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        camera_model: None | str
        camera_model = self.camera_model

        camera_serial: None | str
        camera_serial = self.camera_serial

        lens: None | str
        lens = self.lens

        focal_mm: float | None
        focal_mm = self.focal_mm

        exposure_s: float | None
        exposure_s = self.exposure_s

        aperture: float | None
        aperture = self.aperture

        iso: int | None
        iso = self.iso

        capture_time: None | str
        if isinstance(self.capture_time, datetime.datetime):
            capture_time = self.capture_time.isoformat()
        else:
            capture_time = self.capture_time

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "camera_model": camera_model,
                "camera_serial": camera_serial,
                "lens": lens,
                "focal_mm": focal_mm,
                "exposure_s": exposure_s,
                "aperture": aperture,
                "iso": iso,
                "capture_time": capture_time,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)

        def _parse_camera_model(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        camera_model = _parse_camera_model(d.pop("camera_model"))

        def _parse_camera_serial(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        camera_serial = _parse_camera_serial(d.pop("camera_serial"))

        def _parse_lens(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        lens = _parse_lens(d.pop("lens"))

        def _parse_focal_mm(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        focal_mm = _parse_focal_mm(d.pop("focal_mm"))

        def _parse_exposure_s(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        exposure_s = _parse_exposure_s(d.pop("exposure_s"))

        def _parse_aperture(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        aperture = _parse_aperture(d.pop("aperture"))

        def _parse_iso(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        iso = _parse_iso(d.pop("iso"))

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

        metadata_out = cls(
            camera_model=camera_model,
            camera_serial=camera_serial,
            lens=lens,
            focal_mm=focal_mm,
            exposure_s=exposure_s,
            aperture=aperture,
            iso=iso,
            capture_time=capture_time,
        )

        metadata_out.additional_properties = d
        return metadata_out

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
