"""Token locale per l'autenticazione GUI↔nucleo (ADR-003)."""

from __future__ import annotations

import secrets
import stat
from pathlib import Path

from fastapi import Header, HTTPException, Request, WebSocket, status

TOKEN_BYTES = 32


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def write_token_file(path: Path, token: str) -> None:
    """Scrive il token su disco con permessi riservati al solo utente corrente."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def read_token_file(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value


async def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Dependency FastAPI: verifica il token bearer contro quello generato all'avvio."""
    expected: str = request.app.state.api_token
    supplied = _extract_bearer(authorization)
    if supplied is None or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token mancante o non valido",
            headers={"WWW-Authenticate": "Bearer"},
        )


def websocket_token_valid(websocket: WebSocket, query_token: str | None) -> bool:
    """Verifica il token per il canale WebSocket (header o parametro di query)."""
    expected: str = websocket.app.state.api_token
    header_token = _extract_bearer(websocket.headers.get("authorization"))
    supplied = header_token or query_token
    return supplied is not None and secrets.compare_digest(supplied, expected)
