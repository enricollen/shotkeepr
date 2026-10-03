from http import HTTPStatus
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.api_error import ApiError
from ...models.http_validation_error import HTTPValidationError
from ...models.review_out import ReviewOut
from ...models.review_request import ReviewRequest
from ...types import UNSET, Response, Unset


def _get_kwargs(
    shot_id: UUID,
    *,
    body: ReviewRequest,
    authorization: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(authorization, Unset):
        headers["authorization"] = authorization

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/api/v1/photos/shots/{shot_id}/review".format(
            shot_id=quote(str(shot_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ApiError | HTTPValidationError | ReviewOut | None:
    if response.status_code == 200:
        response_200 = ReviewOut.from_dict(response.json())

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
) -> Response[ApiError | HTTPValidationError | ReviewOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    shot_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: ReviewRequest,
    authorization: None | str | Unset = UNSET,
) -> Response[ApiError | HTTPValidationError | ReviewOut]:
    """Set Photo Review

    Args:
        shot_id (UUID):
        authorization (None | str | Unset):
        body (ReviewRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ApiError | HTTPValidationError | ReviewOut]
    """

    kwargs = _get_kwargs(
        shot_id=shot_id,
        body=body,
        authorization=authorization,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    shot_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: ReviewRequest,
    authorization: None | str | Unset = UNSET,
) -> ApiError | HTTPValidationError | ReviewOut | None:
    """Set Photo Review

    Args:
        shot_id (UUID):
        authorization (None | str | Unset):
        body (ReviewRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ApiError | HTTPValidationError | ReviewOut
    """

    return sync_detailed(
        shot_id=shot_id,
        client=client,
        body=body,
        authorization=authorization,
    ).parsed


async def asyncio_detailed(
    shot_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: ReviewRequest,
    authorization: None | str | Unset = UNSET,
) -> Response[ApiError | HTTPValidationError | ReviewOut]:
    """Set Photo Review

    Args:
        shot_id (UUID):
        authorization (None | str | Unset):
        body (ReviewRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ApiError | HTTPValidationError | ReviewOut]
    """

    kwargs = _get_kwargs(
        shot_id=shot_id,
        body=body,
        authorization=authorization,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    shot_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: ReviewRequest,
    authorization: None | str | Unset = UNSET,
) -> ApiError | HTTPValidationError | ReviewOut | None:
    """Set Photo Review

    Args:
        shot_id (UUID):
        authorization (None | str | Unset):
        body (ReviewRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ApiError | HTTPValidationError | ReviewOut
    """

    return (
        await asyncio_detailed(
            shot_id=shot_id,
            client=client,
            body=body,
            authorization=authorization,
        )
    ).parsed
