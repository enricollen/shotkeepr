from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.settings_out import SettingsOut
from ...models.settings_patch import SettingsPatch
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    body: SettingsPatch,
    authorization: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(authorization, Unset):
        headers["authorization"] = authorization

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/api/v1/settings",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | SettingsOut | None:
    if response.status_code == 200:
        response_200 = SettingsOut.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | SettingsOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: SettingsPatch,
    authorization: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | SettingsOut]:
    """Patch Settings

    Args:
        authorization (None | str | Unset):
        body (SettingsPatch): Campi opzionali: solo quelli presenti vengono aggiornati.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SettingsOut]
    """

    kwargs = _get_kwargs(
        body=body,
        authorization=authorization,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    body: SettingsPatch,
    authorization: None | str | Unset = UNSET,
) -> HTTPValidationError | SettingsOut | None:
    """Patch Settings

    Args:
        authorization (None | str | Unset):
        body (SettingsPatch): Campi opzionali: solo quelli presenti vengono aggiornati.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SettingsOut
    """

    return sync_detailed(
        client=client,
        body=body,
        authorization=authorization,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: SettingsPatch,
    authorization: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | SettingsOut]:
    """Patch Settings

    Args:
        authorization (None | str | Unset):
        body (SettingsPatch): Campi opzionali: solo quelli presenti vengono aggiornati.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SettingsOut]
    """

    kwargs = _get_kwargs(
        body=body,
        authorization=authorization,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: SettingsPatch,
    authorization: None | str | Unset = UNSET,
) -> HTTPValidationError | SettingsOut | None:
    """Patch Settings

    Args:
        authorization (None | str | Unset):
        body (SettingsPatch): Campi opzionali: solo quelli presenti vengono aggiornati.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SettingsOut
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            authorization=authorization,
        )
    ).parsed
