"""
Base synchronization operation.

A SyncOperation describes one atomic synchronization action.

Operations are produced by the Planner after comparing the canonical Archive with the destination state.

Operations are immutable.

They contain no platform-specific logic.

Execution is the responsibility of an OperationExecutor.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SyncOperation(ABC):
    """
    Base class for every synchronization operation.

    Concrete operations represent atomic synchronization work.
    """
