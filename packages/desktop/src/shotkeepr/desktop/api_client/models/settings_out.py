from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.llm_provider_out import LlmProviderOut
    from ..models.settings_out_extra import SettingsOutExtra


T = TypeVar("T", bound="SettingsOut")


@_attrs_define
class SettingsOut:
    """
    Attributes:
        theme (str):
        catalog_enabled (bool):
        edition (str):
        log_level (str):
        llm (LlmProviderOut | None | Unset):
        extra (SettingsOutExtra | Unset):
    """

    theme: str
    catalog_enabled: bool
    edition: str
    log_level: str
    llm: LlmProviderOut | None | Unset = UNSET
    extra: SettingsOutExtra | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.llm_provider_out import LlmProviderOut

        theme = self.theme

        catalog_enabled = self.catalog_enabled

        edition = self.edition

        log_level = self.log_level

        llm: dict[str, Any] | None | Unset
        if isinstance(self.llm, Unset):
            llm = UNSET
        elif isinstance(self.llm, LlmProviderOut):
            llm = self.llm.to_dict()
        else:
            llm = self.llm

        extra: dict[str, Any] | Unset = UNSET
        if not isinstance(self.extra, Unset):
            extra = self.extra.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "theme": theme,
                "catalog_enabled": catalog_enabled,
                "edition": edition,
                "log_level": log_level,
            }
        )
        if llm is not UNSET:
            field_dict["llm"] = llm
        if extra is not UNSET:
            field_dict["extra"] = extra

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.llm_provider_out import LlmProviderOut
        from ..models.settings_out_extra import SettingsOutExtra

        d = dict(src_dict)
        theme = d.pop("theme")

        catalog_enabled = d.pop("catalog_enabled")

        edition = d.pop("edition")

        log_level = d.pop("log_level")

        def _parse_llm(data: object) -> LlmProviderOut | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                llm_type_0 = LlmProviderOut.from_dict(data)

                return llm_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(LlmProviderOut | None | Unset, data)

        llm = _parse_llm(d.pop("llm", UNSET))

        _extra = d.pop("extra", UNSET)
        extra: SettingsOutExtra | Unset
        if isinstance(_extra, Unset):
            extra = UNSET
        else:
            extra = SettingsOutExtra.from_dict(_extra)

        settings_out = cls(
            theme=theme,
            catalog_enabled=catalog_enabled,
            edition=edition,
            log_level=log_level,
            llm=llm,
            extra=extra,
        )

        settings_out.additional_properties = d
        return settings_out

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
