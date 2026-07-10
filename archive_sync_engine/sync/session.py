"""
Synchronization session model.

A SyncSession represents the lifecycle of a single synchronization run.

The session stores engine-owned orchestration state.

Planner state and executor state remain internal implementation details
of those components.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class SyncSession:
    """
    Runtime state for a synchronization session.
    """

    id: str

    started_at: datetime

    updated_at: datetime

    paused: bool = False

    completed: bool = False

    cancelled: bool = False

    error: Optional[str] = None