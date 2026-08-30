"""Logging foundation.

Two requirements shape this module, both from the specification:

* Observability — the runtime must make request, intent, tool call, tool result,
  recommendation, cart, approval, policy, order and payment state observable
  (architecture.md L§42).
* Redaction — secrets must never be logged (L§42, L§45, A§45).

Redaction is implemented as a filter on the logging pipeline rather than as a
rule contributors are asked to remember. Two mechanisms run together: any
configured secret value found in a formatted message is replaced, and any
structured field whose *name* looks secret is replaced. Neither depends on the
author of a log call getting it right.

The standard library is used deliberately: one less dependency, and the
redaction behaviour is explicit and testable rather than inherited.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

REDACTED = "[REDACTED]"

#: Field names whose values are never logged, whatever they contain.
_SENSITIVE_NAME = re.compile(
    r"(api[_-]?key|secret|password|passwd|token|authorization|signature|credential)",
    re.IGNORECASE,
)

#: Log record attributes that belong to logging itself rather than to the event.
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()) | {
    "message",
    "asctime",
    "taskName",
}


class RedactionFilter(logging.Filter):
    """Mask configured secret values and secret-looking fields.

    Attached to handlers rather than to loggers, so it applies to every record
    reaching an output regardless of which logger produced it.
    """

    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        # Very short values are ignored: masking every occurrence of a
        # two-character "secret" would corrupt unrelated log text.
        self._secrets = [s for s in (secrets or []) if len(s) >= 8]

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secrets:
            message = record.getMessage()
            masked = message
            for secret in self._secrets:
                masked = masked.replace(secret, REDACTED)
            if masked != message:
                record.msg = masked
                record.args = ()

        for key, value in list(record.__dict__.items()):
            if key in _STANDARD_ATTRS:
                continue
            if _SENSITIVE_NAME.search(key):
                record.__dict__[key] = REDACTED
            elif isinstance(value, str) and self._secrets:
                for secret in self._secrets:
                    if secret in value:
                        record.__dict__[key] = value.replace(secret, REDACTED)
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for deployed environments."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Readable single-line output for local development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-8s %(name)-28s %(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            key: value for key, value in record.__dict__.items() if key not in _STANDARD_ATTRS
        }
        if extras:
            rendered = " ".join(f"{k}={v!r}" for k, v in sorted(extras.items()))
            return f"{base}  {rendered}"
        return base


def configure_logging(
    *,
    level: str = "INFO",
    fmt: str = "console",
    secrets: list[str] | None = None,
) -> None:
    """Install the root logging configuration. Safe to call more than once."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else ConsoleFormatter())
    handler.addFilter(RedactionFilter(secrets))

    root.addHandler(handler)
    root.setLevel(level)

    # SQLAlchemy's engine logger is noisy at INFO and duplicates DB_ECHO.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
