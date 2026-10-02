# ShotKeepr

Selezione assistita (AI + misure deterministiche) delle foto migliori da raffiche e cluster di
scatti RAW/JPEG. Applicazione desktop locale, nucleo eseguibile in Docker o nativamente.

Licenza: [GNU AGPL-3.0-or-later](LICENSE) · contributi soggetti al [CLA](CLA.md).

## Struttura

| Percorso | Contenuto |
|---|---|
| `packages/core` | `shotkeepr.core` — dominio (`domain/`), casi d'uso e porte (`application/`), adattatori (`adapters/`), API locale (`api/`) |
| `packages/desktop` | `shotkeepr.desktop` — GUI PySide6, comunica col nucleo solo via API |
| `packages/plugin-sdk` | `shotkeepr.plugin_sdk` — SPI versionata per i plugin |
| `docker/` | Immagini del nucleo e `docker compose` |
| `models/` | Manifest dei modelli AI |
| `docs/adr/` | [Architecture Decision Records](docs/adr/README.md) |

## Sviluppo

Requisiti: [mise](https://mise.jdx.dev) (installa Python 3.12 e uv da `.mise.toml`).

```bash
mise install
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run lint-imports        # confini architetturali (ADR-001, ADR-012)
uv run pytest --cov        # copertura minima 80% (NFR-023)
uv run pre-commit install
```

## API locale e client tipizzato

Il nucleo espone `/api/v1` (FastAPI, bind `127.0.0.1`, token locale generato
all'avvio) e un canale WebSocket per gli eventi di avanzamento (ADR-003):

```bash
uv run shotkeepr-core serve [--port N]   # token e porta scritti in <app-data>/run/
```

La GUI parla col nucleo solo via HTTP/WebSocket (ADR-002): `packages/desktop/src/shotkeepr/desktop/api_client/`
è un client tipizzato **generato automaticamente** dal contratto OpenAPI — non va modificato a mano.
Dopo ogni cambio alle rotte del nucleo, rigenerarlo con:

```bash
scripts/generate_client.sh
```

Il canale WebSocket (non descritto da OpenAPI) ha un wrapper scritto a mano in
`packages/desktop/src/shotkeepr/desktop/api_events.py`.
