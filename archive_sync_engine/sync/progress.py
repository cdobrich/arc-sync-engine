"""Adapter-neutral progress events for synchronization runs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SyncProgress:
    """A user-facing synchronization progress event.

    ``phase`` describes the canonical kind of work being executed rather
    than the destination adapter. ``current`` is one-based for completed
    operations within that phase; ``total`` is optional because the planner
    intentionally remains a streaming producer.
    """

    phase: str
    current: int | None = None
    total: int | None = None
    detail: str | None = None
