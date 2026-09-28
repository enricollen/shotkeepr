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
