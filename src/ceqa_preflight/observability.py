"""Minimal, opt-in operational logging that never emits package contents."""

from __future__ import annotations

import json
import logging
from typing import Any

LOGGER = logging.getLogger("ceqa_preflight")


def configure_logging(log_format: str) -> None:
    """Configure package-content-free operational logs on stderr."""

    LOGGER.handlers.clear()
    LOGGER.propagate = False
    if log_format == "json":
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.INFO)
    else:
        LOGGER.setLevel(logging.CRITICAL + 1)


def event(name: str, **fields: str | int | bool) -> None:
    """Emit a safe JSON event only when JSON logging is enabled."""

    if LOGGER.isEnabledFor(logging.INFO):
        payload: dict[str, Any] = {"event": name, **fields}
        LOGGER.info(json.dumps(payload, sort_keys=True))
