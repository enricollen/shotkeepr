#!/usr/bin/env bash
# Rigenera il client tipizzato della GUI dal contratto OpenAPI del nucleo (F1.D2.WP2.A3).
#
# Uso: scripts/generate_client.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

SCHEMA=$(mktemp /tmp/shotkeepr-openapi-XXXXXX.json)
TARGET="packages/desktop/src/shotkeepr/desktop/api_client"
OUT=$(mktemp -d /tmp/shotkeepr-client-XXXXXX)
trap 'rm -rf "$SCHEMA" "$OUT"' EXIT

uv run python scripts/export_openapi.py "$SCHEMA"
rm -rf "$OUT"
uv run openapi-python-client generate --path "$SCHEMA" --config scripts/openapi-client.yaml --output-path "$OUT" --meta none

rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -r "$OUT"/* "$TARGET"/
rm -rf "$TARGET/.ruff_cache"

# Ripristina gli header "generato automaticamente" e il wrapper WebSocket scritto a mano.
python3 - "$TARGET/__init__.py" <<'PY'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
old = '"""A client library for accessing ShotKeepr core API"""'
new = (
    '"""A client library for accessing ShotKeepr core API.\n\n'
    "GENERATO AUTOMATICAMENTE da `scripts/generate_client.sh` a partire dal contratto\n"
    "OpenAPI del nucleo (F1.D2.WP2.A3). Non modificare a mano: rigenerare dopo ogni\n"
    'cambio delle rotte `/api/v1`.\n"""'
)
open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))
PY

echo "Client rigenerato in $TARGET"
