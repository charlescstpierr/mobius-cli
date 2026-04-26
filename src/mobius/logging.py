"""Stderr-only logging helpers for Mobius."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_DEFAULT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DEFAULT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class JsonLogFormatter(logging.Formatter):
    """Format stdlib log records as compact JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        """Return one JSON log line for *record*."""
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(
    *,
    level: str | int = "INFO",
    json_output: bool = False,
    force: bool = False,
) -> None:
    """Configure all stdlib log records to use stderr.

    Stdout is reserved for command data, so this function installs a single
    ``sys.stderr`` stream handler on the root logger. ``force`` is accepted for
    call-site clarity; Mobius always replaces prior root handlers so accidental
    stdout handlers cannot leak log records into command data.
    """
    root_logger = logging.getLogger()
    handler = logging.StreamHandler(stream=sys.stderr)
    if json_output:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATE_FORMAT))

    root_logger.handlers = [handler]
    root_logger.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Return a stdlib logger after ensuring stderr-only logging is configured."""
    configure_logging()
    return logging.getLogger(name)
