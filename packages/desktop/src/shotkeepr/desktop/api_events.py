"""Client tipizzato per il canale WebSocket degli eventi (ADR-003).

Scritto a mano: OpenAPI 3.x non descrive i canali WebSocket, quindi non rientra
nella generazione automatica di `scripts/generate_client.sh`. Il contratto dei
messaggi (``kind``/``payload``/``at``) rispecchia ``shotkeepr.core.api.events.Event``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


class EventKind(StrEnum):
    PROGRESS = "PROGRESS"
    NOTIFICATION = "NOTIFICATION"
    DEGRADATION = "DEGRADATION"


@dataclass(frozen=True, slots=True)
class ServerEvent:
    kind: EventKind
    payload: dict[str, Any]
    at: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ServerEvent:
        return cls(kind=EventKind(data["kind"]), payload=data["payload"], at=data["at"])


@asynccontextmanager
async def events_channel(base_url: str, token: str) -> AsyncIterator[AsyncIterator[ServerEvent]]:
    """Apre il canale `/api/v1/events` e consegna un iteratore asincrono di eventi.

    `base_url` è l'origine HTTP del nucleo (es. ``http://127.0.0.1:8321``), tradotta
    internamente nello schema ``ws``/``wss``.
    """
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    uri = f"{ws_url}/api/v1/events?token={token}"

    async def _iterate(connection: Any) -> AsyncIterator[ServerEvent]:
        try:
            async for message in connection:
                yield ServerEvent.from_json(_loads(message))
        except ConnectionClosed:
            return

    async with connect(uri) as connection:
        yield _iterate(connection)


def _loads(message: str | bytes) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(message)
    return result
