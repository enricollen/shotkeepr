from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.api_error import ApiError
from ...models.http_validation_error import HTTPValidationError
from ...models.shot_page_out import ShotPageOut
from ...types import UNSET, Response, Unset


def _get_kwargs(
    session_id: UUID,
    *,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
    group_id: None | Unset | UUID = UNSET,
    ungrouped: bool | Unset = False,
    authorization: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(authorization, Unset):
        headers["authorization"] = authorization

    params: dict[str, Any] = {}

    params["limit"] = limit

    params["offset"] = offset

    json_group_id: None | str | Unset
    if isinstance(group_id, Unset):
        json_group_id = UNSET
    elif isinstance(group_id, UUID):
        json_group_id = str(group_id)
    else:
        json_group_id = group_id
    params["group_id"] = json_group_id

    params["ungrouped"] = ungrouped

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/photos/sessions/{session_id}/shots".format(
            session_id=quote(str(session_id), safe=""),
        ),
        "params": params,
    }

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ApiError | HTTPValidationError | ShotPageOut | None:
    if response.status_code == 200:
        response_200 = ShotPageOut.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = ApiError.from_dict(response.json())

        return response_400

    if response.status_code == 404:
        response_404 = ApiError.from_dict(response.json())

        return response_404

    if response.status_code == 409:
        response_409 = ApiError.from_dict(response.json())

        return response_409

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if response.status_code == 503:
        response_503 = ApiError.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ApiError | HTTPValidationError | ShotPageOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    session_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
    group_id: None | Unset | UUID = UNSET,
    ungrouped: bool | Unset = False,
    authorization: None | str | Unset = UNSET,
) -> Response[ApiError | HTTPValidationError | ShotPageOut]:
    """List Photo Shots

    Args:
        session_id (UUID):
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.
        group_id (None | Unset | UUID):
        ungrouped (bool | Unset):  Default: False.
        authorization (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ApiError | HTTPValidationError | ShotPageOut]
    """

    kwargs = _get_kwargs(
        session_id=session_id,
        limit=limit,
        offset=offset,
        group_id=group_id,
        ungrouped=ungrouped,
        authorization=authorization,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    session_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
    group_id: None | Unset | UUID = UNSET,
    ungrouped: bool | Unset = False,
    authorization: None | str | Unset = UNSET,
) -> ApiError | HTTPValidationError | ShotPageOut | None:
    """List Photo Shots

    Args:
        session_id (UUID):
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.
        group_id (None | Unset | UUID):
        ungrouped (bool | Unset):  Default: False.
        authorization (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ApiError | HTTPValidationError | ShotPageOut
    """

    return sync_detailed(
        session_id=session_id,
        client=client,
        limit=limit,
        offset=offset,
        group_id=group_id,
        ungrouped=ungrouped,
        authorization=authorization,
    ).parsed


async def asyncio_detailed(
    session_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
    group_id: None | Unset | UUID = UNSET,
    ungrouped: bool | Unset = False,
    authorization: None | str | Unset = UNSET,
) -> Response[ApiError | HTTPValidationError | ShotPageOut]:
    """List Photo Shots

    Args:
        session_id (UUID):
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.
        group_id (None | Unset | UUID):
        ungrouped (bool | Unset):  Default: False.
        authorization (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ApiError | HTTPValidationError | ShotPageOut]
    """

    kwargs = _get_kwargs(
        session_id=session_id,
        limit=limit,
        offset=offset,
        group_id=group_id,
        ungrouped=ungrouped,
        authorization=authorization,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    session_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
    group_id: None | Unset | UUID = UNSET,
    ungrouped: bool | Unset = False,
    authorization: None | str | Unset = UNSET,
) -> ApiError | HTTPValidationError | ShotPageOut | None:
    """List Photo Shots

    Args:
        session_id (UUID):
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.
        group_id (None | Unset | UUID):
        ungrouped (bool | Unset):  Default: False.
        authorization (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ApiError | HTTPValidationError | ShotPageOut
    """

    return (
        await asyncio_detailed(
            session_id=session_id,
            client=client,
            limit=limit,
            offset=offset,
            group_id=group_id,
            ungrouped=ungrouped,
            authorization=authorization,
        )
    ).parsed
