"""
Import session model.

An ImportSession represents the lifecycle of one acquisition run.

The session stores engine-owned orchestration state.

Importer-specific progress is stored separately as an ImportState.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .state import ImportState


@dataclass(slots=True)
class ImportSession:
    """
    Runtime state for a single import session.
    """

    started_at: datetime

    updated_at: datetime

    state: Optional[ImportState] = None

    paused: bool = False

    completed: bool = False

    cancelled: bool = False

    error: Optional[str] = None
