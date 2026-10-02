"""A client library for accessing ShotKeepr core API.

GENERATO AUTOMATICAMENTE da `scripts/generate_client.sh` a partire dal contratto
OpenAPI del nucleo (F1.D2.WP2.A3). Non modificare a mano: rigenerare dopo ogni
cambio delle rotte `/api/v1`.
"""

from .client import AuthenticatedClient, Client

__all__ = (
    "AuthenticatedClient",
    "Client",
)
