"""Canale WebSocket per eventi di avanzamento, notifiche e degrado (ADR-003)."""

from __future__ import annotations

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from shotkeepr.core.api.auth import websocket_token_valid
from shotkeepr.core.api.events import EventBus

router = APIRouter(tags=["events"])


@router.websocket("/events")
async def events_ws(websocket: WebSocket, token: str | None = None) -> None:
    if not websocket_token_valid(websocket, token):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    bus: EventBus = websocket.app.state.event_bus
    subscription = bus.subscribe()
    try:
        while True:
            event = await anyio.to_thread.run_sync(subscription.get, abandon_on_cancel=True)
            await websocket.send_json(event.to_json())
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(subscription)
