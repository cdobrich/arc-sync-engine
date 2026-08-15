"""Application logging and safe error-reporting helpers for the CLI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

LOGGER_NAME = "archive_sync_engine"


class RedactingFormatter(logging.Formatter):
    """Formatter that removes known secret values from log messages."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
        self._secrets = tuple(secret for secret in secrets if secret)

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        for secret in self._secrets:
            message = message.replace(secret, "[REDACTED]")
        return message


def configure_logging(
    *,
    level: str = "WARNING",
    log_file: Path | None = None,
    secrets: Iterable[str] = (),
) -> logging.Logger:
    """Configure the application logger without modifying the root logger."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(getattr(logging, level.upper()))
    logger.propagate = False

    formatter = RedactingFormatter(secrets)
    stream = logging.StreamHandler()
    stream.setLevel(logger.level)
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    if log_file is not None:
        path = log_file.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setLevel(logger.level)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def get_logger() -> logging.Logger:
    """Return the application logger."""

    return logging.getLogger(LOGGER_NAME)


def report_expected_error(exc: Exception) -> None:
    """Record a user-actionable application error without a traceback."""

    get_logger().error("%s: %s", type(exc).__name__, exc)


def report_unexpected_error(exc: Exception) -> None:
    """Record an unexpected failure with traceback for troubleshooting."""

    get_logger().exception("Unhandled application error: %s", exc)
