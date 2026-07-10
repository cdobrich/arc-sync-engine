"""
Synchronization operation executor interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from archive_sync_engine.adapters import DestinationAdapter
from archive_sync_engine.operations import SyncOperation

from .result import ExecutionResult


class OperationExecutor(ABC):
    """
    Executes synchronization operations.

    The executor performs exactly one operation.

    It never performs planning.

    It never performs persistence.
    """

    @abstractmethod
    def execute(
        self,
        operation: SyncOperation,
        destination: DestinationAdapter,
    ) -> ExecutionResult:
        """
        Execute one synchronization operation.
        """
        raise NotImplementedError
