"""Log JSON su file con rotazione; credenziali e segreti sono sempre redatti."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

MASK = "***"
_SENSITIVE_KEY = re.compile(r"(api[_-]?key|token|secret|password|passwd|authorization)", re.I)
_PATTERNS = [
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd)\b(\s*[=:]\s*)(\"?)[^\s\"&,;]+"),
]
_STD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{MASK}", text)
        elif pattern.groups == 1:
            text = pattern.sub(lambda m: f"{m.group(1)} {MASK}", text)
        else:
            text = pattern.sub(MASK, text)
    return text


def _redact_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEY.search(key):
        return MASK
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(key, v) for v in value]
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        for key, value in list(vars(record).items()):
            if key not in _STD_ATTRS:
                setattr(record, key, _redact_value(key, value))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = {k: v for k, v in vars(record).items() if k not in _STD_ATTRS}
        if extra:
            payload["ctx"] = extra
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(
    log_dir: Path | None,
    level: str = "INFO",
    *,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
    console: bool = True,
) -> logging.Logger:
    root = logging.getLogger("shotkeepr")
    root.setLevel(level)
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    handlers: list[logging.Handler] = []
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_dir / "shotkeepr.log",
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
        )
    if console:
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.addFilter(RedactingFilter())
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    return root
