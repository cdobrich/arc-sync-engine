"""Configurable synchronous pacing for import and export operations."""

from __future__ import annotations

import time
from collections.abc import Callable


class OperationRateLimiter:
    """Apply configured delays between channel and message operations.

    The limiter is deliberately independent of any source or destination
    adapter.  It paces the engine's canonical work boundary, so the same
    configured delays apply to both import and export workflows.
    """

    def __init__(
        self,
        *,
        between_messages_seconds: float = 0.0,
        between_channels_seconds: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if between_messages_seconds < 0:
            raise ValueError("between_messages_seconds must be non-negative.")
        if between_channels_seconds < 0:
            raise ValueError("between_channels_seconds must be non-negative.")

        self._message_delay = float(between_messages_seconds)
        self._channel_delay = float(between_channels_seconds)
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_message_at: float | None = None
        self._last_channel_at: float | None = None

    @property
    def between_messages_seconds(self) -> float:
        return self._message_delay

    @property
    def between_channels_seconds(self) -> float:
        return self._channel_delay

    def before_message(self) -> None:
        """Wait until the configured message interval has elapsed."""
        self._wait(self._last_message_at, self._message_delay)
        self._last_message_at = self._monotonic()

    def before_channel(self) -> None:
        """Wait until the configured channel interval has elapsed."""
        self._wait(self._last_channel_at, self._channel_delay)
        self._last_channel_at = self._monotonic()

    def _wait(self, last_at: float | None, delay: float) -> None:
        if last_at is None or delay <= 0:
            return
        remaining = delay - (self._monotonic() - last_at)
        if remaining > 0:
            self._sleep(remaining)
