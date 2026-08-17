"""
Synchronization coordinator.

The coordinator does exactly five things:

- Load the current synchronization state.
- Ask the planner for an ordered stream of SyncOperations.
- Execute each operation in order.
- Apply successful execution results to the synchronization state.
- Persist the resulting synchronization state.

It deliberately does not:

- inspect individual operations,
- reorder operations,
- contain destination-specific logic,
- implement planning algorithms,
- implement persistence logic.
"""

from __future__ import annotations

from collections.abc import Iterator

from archive_sync_engine.archive import Archive
from archive_sync_engine.adapters import (
    DestinationAdapter,
    DestinationCapabilities,
)
from archive_sync_engine.executor import (
    ExecutionContext,
    ExecutionResult,
    OperationExecutor,
)
from archive_sync_engine.operations import SyncOperation
from archive_sync_engine.planner import Planner
from archive_sync_engine.repository import StateRepository

from .synchronization_state import SynchronizationState


class SyncCoordinator:
    """
    Coordinates one synchronization run.

    The coordinator orchestrates planning, execution, synchronization
    state updates, and persistence.

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

    def dry_run(self) -> tuple[SyncOperation, ...]:
        """Plan synchronization without executing or persisting anything.

        Dry-run planning loads the current synchronization state and asks the
        Planner for the complete validated operation stream. It deliberately
        does not call the executor, mutate the destination, or persist state.
        """
        synchronization_state: SynchronizationState = (
            self._state_repository.load_synchronization_state()
        )

        return tuple(
            self._planner.plan(
                archive=self._archive,
                synchronization_state=synchronization_state,
                capabilities=self._capabilities,
            )
        )

    def synchronize(self) -> tuple[ExecutionResult, ...]:
        """
        Perform one synchronization run.

        Each operation is executed in the exact order produced by the
        Planner.

        After a successful execution, the resulting destination reference
        is applied to the synchronization state and the complete new state
        is persisted.

        If execution raises an exception, the exception propagates and no
        execution result is recorded for that operation.

        Returns the successful execution results in planner order.
        """

        synchronization_state: SynchronizationState = (
            self._state_repository.load_synchronization_state()
        )

        execution_context = ExecutionContext.from_synchronization_state(
            synchronization_state,
        )

        results: list[ExecutionResult] = []

        operations: Iterator[SyncOperation] = self._planner.plan(
            archive=self._archive,
            synchronization_state=synchronization_state,
            capabilities=self._capabilities,
        )

        for operation in operations:
            result: ExecutionResult = self._executor.execute(
                operation=operation,
                destination=self._destination,
                context=execution_context,
            )

            synchronization_state = (
                synchronization_state.apply_execution_result(
                    canonical_id=result.canonical_id,
                    result=result,
                )
            )

            self._state_repository.record_execution(
                operation=operation,
                result=result,
                synchronization_state=synchronization_state,
            )
            results.append(result)

        return tuple(results)
