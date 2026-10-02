"""Esporta lo schema OpenAPI del nucleo, per generare il client tipizzato della GUI.

Uso: `uv run python scripts/export_openapi.py [output_path]`
L'app è costruita con un token e un servizio di configurazione fittizi: lo schema
dipende solo dalla struttura delle rotte, non dallo stato.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core" / "src"))

from shotkeepr.core.api.app import create_app


class _NullSecretStore:
    def get(self, ref: str) -> str | None:
        return None

    def set(self, ref: str, secret: str) -> None:
        return None

    def delete(self, ref: str) -> None:
        return None


class _NullSettingsRepository:
    def load(self) -> None:
        return None

    def save(self, settings: object) -> None:
        return None


def main() -> None:
    from shotkeepr.core.application.configuration import ConfigurationService

    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    service = ConfigurationService(_NullSettingsRepository(), _NullSecretStore())  # type: ignore[arg-type]
    app = create_app(service, api_token="export-only")
    output.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Schema OpenAPI scritto in {output}")


if __name__ == "__main__":
    main()
