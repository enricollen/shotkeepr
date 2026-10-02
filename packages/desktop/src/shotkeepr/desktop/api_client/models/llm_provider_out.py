from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="LlmProviderOut")


@_attrs_define
class LlmProviderOut:
    """
    Attributes:
        provider (str):
        model (str):
        endpoint (None | str | Unset):
        send_image (bool | Unset):  Default: False.
        timeout_s (float | Unset):  Default: 10.0.
    """

    provider: str
    model: str
    endpoint: None | str | Unset = UNSET
    send_image: bool | Unset = False
    timeout_s: float | Unset = 10.0
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        provider = self.provider

        model = self.model

        endpoint: None | str | Unset
        if isinstance(self.endpoint, Unset):
            endpoint = UNSET
        else:
            endpoint = self.endpoint

        send_image = self.send_image

        timeout_s = self.timeout_s

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "provider": provider,
                "model": model,
            }
        )
        if endpoint is not UNSET:
            field_dict["endpoint"] = endpoint
        if send_image is not UNSET:
            field_dict["send_image"] = send_image
        if timeout_s is not UNSET:
            field_dict["timeout_s"] = timeout_s

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        provider = d.pop("provider")

        model = d.pop("model")

        def _parse_endpoint(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        endpoint = _parse_endpoint(d.pop("endpoint", UNSET))

        send_image = d.pop("send_image", UNSET)

        timeout_s = d.pop("timeout_s", UNSET)

        llm_provider_out = cls(
            provider=provider,
            model=model,
            endpoint=endpoint,
            send_image=send_image,
            timeout_s=timeout_s,
        )

        llm_provider_out.additional_properties = d
        return llm_provider_out

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
