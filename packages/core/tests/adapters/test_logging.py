from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from shotkeepr.core.adapters.observability import configure_logging, redact


@pytest.mark.parametrize(
    ("raw", "leak"),
    [
        ("Authorization: Bearer abc.def-123", "abc.def-123"),
        ("key sk-proj-ABCDEFGH1234", "sk-proj-ABCDEFGH1234"),
        ("api_key=supersecret&x=1", "supersecret"),
        ('password: "hunter2"', "hunter2"),
        ("token ghp_ABCDEFGHIJKLMNOPQRSTUV12", "ghp_ABCDEFGHIJKLMNOPQRSTUV12"),
        ("gemini AIzaSyA1234567890abcdefghijk", "AIzaSyA1234567890abcdefghijk"),
    ],
)
def test_redact(raw: str, leak: str) -> None:
    out = redact(raw)
    assert leak not in out
    assert "***" in out


def test_redact_keeps_normal_text() -> None:
    assert (
        redact("Analizzati 120 scatti in /photos/sposi") == "Analizzati 120 scatti in /photos/sposi"
    )


def test_json_file_logging_with_rotation_and_redaction(tmp_path: Path) -> None:
    logger = configure_logging(tmp_path, "DEBUG", max_bytes=2000, backup_count=2, console=False)
    log = logging.getLogger("shotkeepr.test")
    log.info("chiave %s", "sk-abcdefghijk", extra={"api_key": "x", "shots": 3, "d": {"token": 1}})
    try:
        raise RuntimeError("password=boom")
    except RuntimeError:
        log.exception("errore")
    for i in range(40):
        log.debug("riga %d", i)
    for h in logger.handlers:
        h.flush()
    files = sorted(tmp_path.glob("shotkeepr.log*"))
    assert len(files) == 3
    content = "".join(f.read_text() for f in files)
    assert "sk-abcdefghijk" not in content
    assert "boom" not in content
    records = [json.loads(line) for f in files for line in f.read_text().splitlines()]
    first = next(r for r in records if r["level"] == "INFO")
    assert first["ctx"] == {"api_key": "***", "shots": 3, "d": {"token": "***"}}
    configure_logging(None, console=True)
    assert len(logging.getLogger("shotkeepr").handlers) == 1
