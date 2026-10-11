"""Adapter-neutral progress events for canonical imports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImportProgress:
    """A user-facing import progress event.

    ``phase`` is intentionally adapter-neutral. ``current`` and ``total``
    are optional because a source may expose a stream whose size cannot be
    known without an additional acquisition pass. For conversation progress,
    ``current`` identifies the conversation being processed and ``completed``
    identifies how many conversations have finished successfully.
    """

    phase: str
    current: int | None = None
    total: int | None = None
    completed: int | None = None
    detail: str | None = None
    mode: str | None = None
    cursor: str | None = None
    lookback_seconds: float | None = None
    traversal: str | None = None
    examined: int | None = None
    attachments_downloaded: int | None = None
    attachments_reused: int | None = None
    conversations_scanned: int | None = None
    messages_added: int | None = None
    messages_existing: int | None = None
    reply_targets_recovered: int | None = None
    unresolved_reply_targets: int | None = None
