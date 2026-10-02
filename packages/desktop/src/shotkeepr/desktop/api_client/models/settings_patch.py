from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.log_level import LogLevel
from ..models.theme import Theme
from ..types import UNSET, Unset

T = TypeVar("T", bound="SettingsPatch")


@_attrs_define
class SettingsPatch:
    """Campi opzionali: solo quelli presenti vengono aggiornati.

    Attributes:
        theme (None | Theme | Unset):
        catalog_enabled (bool | None | Unset):
        log_level (LogLevel | None | Unset):
    """

    theme: None | Theme | Unset = UNSET
    catalog_enabled: bool | None | Unset = UNSET
    log_level: LogLevel | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        theme: None | str | Unset
        if isinstance(self.theme, Unset):
            theme = UNSET
        elif isinstance(self.theme, Theme):
            theme = self.theme.value
        else:
            theme = self.theme

        catalog_enabled: bool | None | Unset
        if isinstance(self.catalog_enabled, Unset):
            catalog_enabled = UNSET
        else:
            catalog_enabled = self.catalog_enabled

        log_level: None | str | Unset
        if isinstance(self.log_level, Unset):
            log_level = UNSET
        elif isinstance(self.log_level, LogLevel):
            log_level = self.log_level.value
        else:
            log_level = self.log_level

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if theme is not UNSET:
            field_dict["theme"] = theme
        if catalog_enabled is not UNSET:
            field_dict["catalog_enabled"] = catalog_enabled
        if log_level is not UNSET:
            field_dict["log_level"] = log_level

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)

        def _parse_theme(data: object) -> None | Theme | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                theme_type_0 = Theme(data)

                return theme_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Theme | Unset, data)

        theme = _parse_theme(d.pop("theme", UNSET))

        def _parse_catalog_enabled(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        catalog_enabled = _parse_catalog_enabled(d.pop("catalog_enabled", UNSET))

        def _parse_log_level(data: object) -> LogLevel | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                log_level_type_0 = LogLevel(data)

                return log_level_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(LogLevel | None | Unset, data)

        log_level = _parse_log_level(d.pop("log_level", UNSET))

        settings_patch = cls(
            theme=theme,
            catalog_enabled=catalog_enabled,
            log_level=log_level,
        )

        settings_patch.additional_properties = d
        return settings_patch

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
