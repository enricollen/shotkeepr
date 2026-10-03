"""Sonda di liveness locale, senza dipendenze HTTP aggiuntive."""

from __future__ import annotations

import json
from http.client import HTTPConnection

from shotkeepr.core.api.server import LOCALHOST


class HealthCheckError(RuntimeError):
    """Il nucleo risponde, ma non dichiara uno stato sano."""


def check_health(port: int, *, timeout: float = 2.0) -> None:
    if not 0 < port < 65536:
        raise ValueError("la porta deve essere compresa tra 1 e 65535")
    connection = HTTPConnection(LOCALHOST, port, timeout=timeout)
    try:
        connection.request("GET", "/api/v1/health")
        response = connection.getresponse()
        if response.status != 200:
            raise HealthCheckError(f"il nucleo ha risposto con HTTP {response.status}")
        # Limita la lettura anche se un servizio diverso occupa la porta configurata.
        body = response.read(4097)
        if len(body) > 4096:
            raise HealthCheckError("risposta di salute troppo grande")
        payload = json.loads(body)
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            raise HealthCheckError("il nucleo non dichiara status=ok")
    finally:
        connection.close()
