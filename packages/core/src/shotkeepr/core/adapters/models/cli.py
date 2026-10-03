"""Gestione headless dei modelli, senza caricare ONNX durante l'avvio dell'API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shotkeepr.core.adapters.models.artifacts import VerifiedModelStore, load_manifest
from shotkeepr.core.adapters.paths import app_data_dir
from shotkeepr.core.application.models import ModelRegistry
from shotkeepr.core.domain.models.model import Device, ModelError


def configure_models_cli(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="model_command", required=True)
    providers = commands.add_parser("providers", help="Elenca i provider ONNX disponibili")
    providers.add_argument("--device", choices=list(Device), default=Device.AUTO.value)
    for command, help_text in (
        ("list", "Elenca gli artefatti approvati nel manifest"),
        ("fetch", "Scarica i pesi e verifica SHA-256 e dimensione"),
        ("verify", "Verifica la cache senza accedere alla rete"),
        ("validate", "Verifica i pesi e apre una sessione ONNX"),
    ):
        action = commands.add_parser(command, help=help_text)
        action.add_argument("--manifest", type=Path, default=Path("models/manifest.json"))
        action.add_argument("--cache-dir", type=Path, default=None)
        if command != "list":
            action.add_argument("model_id")
            action.add_argument("--version", default=None)
        if command == "validate":
            action.add_argument("--device", choices=list(Device), default=Device.AUTO.value)


def _providers(device: str) -> dict[str, object]:
    from shotkeepr.core.adapters.models.runtime import (  # noqa: PLC0415
        available_providers,
        select_providers,
    )

    available = available_providers()
    return {
        "available_providers": available,
        "preferred_providers": select_providers(available, Device(device)),
        "initialized": False,
    }


def _validate(path: Path, device: str) -> dict[str, object]:
    from shotkeepr.core.adapters.models.runtime import OnnxModelSession  # noqa: PLC0415

    session = OnnxModelSession(path, device=Device(device))
    return {
        "runtime": session.info.to_dict(),
        "inputs": session.input_names,
        "outputs": session.output_names,
    }


def run_models(args: argparse.Namespace) -> int:
    try:
        if args.model_command == "providers":
            result = _providers(args.device)
        else:
            manifest = load_manifest(args.manifest)
            if args.model_command == "list":
                print(json.dumps(manifest.to_dict(), indent=2))
                return 0
            root = args.cache_dir if args.cache_dir is not None else app_data_dir() / "models"
            registry = ModelRegistry(manifest, VerifiedModelStore(root))
            artifact = manifest.select(args.model_id, args.version)
            if args.model_command == "fetch":

                def progress(received: int, total: int) -> None:
                    print(f"{artifact.model_id}: {received}/{total} byte", file=sys.stderr)

                path = registry.fetch(args.model_id, args.version, progress=progress)
            else:
                path = registry.verify(args.model_id, args.version)
            result = {
                "model_id": artifact.model_id,
                "version": artifact.version,
                "path": str(path),
                "verified": True,
            }
            if args.model_command == "validate":
                result.update(_validate(path, args.device))
        print(json.dumps(result, indent=2))
    except (ModelError, OSError, ValueError) as exc:
        print(f"Modello non disponibile: {exc}", file=sys.stderr)
        return 1
    return 0
