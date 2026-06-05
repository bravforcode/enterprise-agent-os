"""Enterprise Agent OS — Structured logging (stdlib only, no structlog)."""
from __future__ import annotations
import logging
import sys
from .config import settings


def setup_logging() -> None:
    """Configure stdlib logging."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        stream=sys.stderr,
    )


def get_logger(name: str) -> logging.Logger:
    """Get a named logger."""
    return logging.getLogger(f"graxia_tool.{name}")
