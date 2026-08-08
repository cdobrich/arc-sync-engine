"""
Synchronization plan.

A SynchronizationPlan contains the ordered operations produced by the
Planner. It contains no destination-specific state and performs no
execution.
"""

from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.operations import SyncOperation


@dataclass(frozen=True, slots=True)
class SynchronizationPlan:
    """
    Ordered synchronization operations.

    The order of operations is significant and must be preserved exactly
    as produced by the Planner.
    """

    operations: tuple[SyncOperation, ...]

    def __iter__(self):
        """
        Iterate over operations in execution order.
        """

        return iter(self.operations)

    def __len__(self) -> int:
        """
        Return the number of planned operations.
        """

        return len(self.operations)

    def __bool__(self) -> bool:
        """
        Return whether the plan contains operations.
        """

        return bool(self.operations)