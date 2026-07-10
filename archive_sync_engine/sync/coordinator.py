"""
Synchronization coordinator.

The coordinator does exactly four things:
- Query the destination's capabilities.
- Ask the planner for an ordered stream of SyncOperations.
- Execute each operation in order.
- Return when synchronization is complete.

It deliberately does not:
- inspect individual operations,
- reorder operations,
- contain destination-specific logic,
- implement planning algorithms.

"""

from __future__ import annotations

from collections.abc import Iterator

from archive_sync_engine.archive import Archive
from archive_sync_engine.adapters import (
    DestinationAdapter,
    DestinationCapabilities,
)
from archive_sync_engine.executor import OperationExecutor
from archive_sync_engine.operations import SyncOperation
from archive_sync_engine.planner import Planner
from archive_sync_engine.repository import StateRepository

from .synchronization_state import SynchronizationState



class SyncCoordinator:
    """
    Coordinates one synchronization run.

    The coordinator orchestrates planning and execution.

    It does not implement planning or execution logic itself.
    """

    def __init__(
        self,
        *,
        archive: Archive,
        planner: Planner,
        executor: OperationExecutor,
        destination: DestinationAdapter,
        capabilities: DestinationCapabilities,
        state_repository: StateRepository,
    ) -> None:
        self._archive = archive
        self._planner = planner
        self._executor = executor
        self._destination = destination
        self._capabilities = capabilities
        self._state_repository = state_repository

    def synchronize(self) -> None:
        """
        Perform one synchronization run.
        """

        synchronization_state: SynchronizationState = (
            self._state_repository.load_synchronization_state()
        )

        operations: Iterator[SyncOperation] = self._planner.plan(
            archive=self._archive,
            synchronization_state=synchronization_state,
            capabilities=self._capabilities,
        )

        for operation in operations:
            self._executor.execute(
                operation=operation,
                destination=self._destination,
            )
