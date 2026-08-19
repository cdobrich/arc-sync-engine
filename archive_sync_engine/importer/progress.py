"""Adapter-neutral progress events for canonical imports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImportProgress:
    """A user-facing import progress event.

    ``phase`` is intentionally adapter-neutral. ``current`` and ``total``
    are optional because a source may expose a stream whose size cannot be
    known without an additional acquisition pass.
    """

    phase: str
    current: int | None = None
    total: int | None = None
    detail: str | None = None
    mode: str | None = None
    cursor: str | None = None
    lookback_seconds: float | None = None
    traversal: str | None = None
    examined: int | None = None
    attachments_downloaded: int | None = None
    attachments_reused: int | None = None
