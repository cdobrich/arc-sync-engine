"""
In-memory StateRepository implementation.

This repository is intended for tests and early engine integration.

It provides the same persistence semantics as the StateRepository
interface without introducing database concerns.
"""

from __future__ import annotations

from archive_sync_engine.executor import ExecutionResult
from archive_sync_engine.importer import ImportSession
from archive_sync_engine.operations import SyncOperation
from archive_sync_engine.sync import SynchronizationState

from .state_repository import StateRepository


class InMemoryStateRepository(StateRepository):
    """
    In-memory implementation of StateRepository.

    Synchronization state is replaced atomically whenever an execution
    is recorded.

    Import-session persistence is intentionally minimal because the
    import pipeline has not yet implemented its execution semantics.
    """

    def __init__(
        self,
        *,
        synchronization_state: SynchronizationState | None = None,
    ) -> None:
        self._synchronization_state = (
            synchronization_state
            if synchronization_state is not None
            else SynchronizationState()
        )

        self._import_session: ImportSession | None = None

    def save_import_session(
        self,
        session: ImportSession,
    ) -> None:
        """
        Persist the current import session.
        """

        self._import_session = session

    def load_import_session(
        self,
    ) -> ImportSession | None:
        """
        Load the most recently persisted import session.
        """

        return self._import_session

    def load_synchronization_state(
        self,
    ) -> SynchronizationState:
        """
        Return the current synchronization-state snapshot.
        """

        return self._synchronization_state

    def record_execution(
        self,
        operation: SyncOperation,
        result: ExecutionResult,
        synchronization_state: SynchronizationState,
    ) -> None:
        """
        Persist the supplied post-execution synchronization state.

        The coordinator is responsible for producing the new immutable
        state. The repository persists that complete snapshot rather
        than interpreting the operation or execution result.
        """

        self._synchronization_state = synchronization_state