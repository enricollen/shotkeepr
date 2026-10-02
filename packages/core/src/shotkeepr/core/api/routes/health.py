"""Rotta di salute (pubblica, nessuna autenticazione): liveness del nucleo."""

from __future__ import annotations

from fastapi import APIRouter

from shotkeepr.core.api.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def get_health() -> HealthOut:
    return HealthOut()
