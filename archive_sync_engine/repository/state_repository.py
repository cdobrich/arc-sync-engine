"""
State Repository interface.

StateRepositories persist operational metadata required by the engine.

Canonical entities belong in the Archive.

State Repositories intentionally do not own canonical content.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from archive_sync_engine.executor import ExecutionResult
from archive_sync_engine.importer import ImportSession
from archive_sync_engine.operations import SyncOperation
from archive_sync_engine.sync import SynchronizationState

from .execution_log import ExecutionLogEntry


class StateRepository(ABC):
    """
    Persistence interface for engine metadata.
    """

    #
    # Import sessions
    #

    @abstractmethod
    def save_import_session(
        self,
        session: ImportSession,
    ) -> None:
        """
        Persist an import session.
        """
        raise NotImplementedError

    @abstractmethod
    def load_import_session(
        self,
    ) -> ImportSession | None:
        """
        Load the most recent import session.

        Returns None if no previous session exists.
        """
        raise NotImplementedError
    
    @abstractmethod
    def load_synchronization_state(
        self,
    ) -> SynchronizationState:
        """
        Load the current synchronization metadata snapshot.
        """
        raise NotImplementedError

    @abstractmethod
    def record_execution(
            self,
            operation: SyncOperation,
            result: ExecutionResult,
            synchronization_state: SynchronizationState,
    ) -> None:
        """
        Persist synchronization metadata resulting from a
        successfully executed operation.

        The Coordinator calls this method only after the operation has
        executed successfully and the supplied state has been transitioned
        to reflect that success. Implementations must not decide whether an
        operation succeeded or perform synchronization logic themselves.

        The supplied synchronization state represents the complete
        post-execution snapshot and must be persisted atomically with
        the execution metadata.
        """
        raise NotImplementedError
    @abstractmethod
    def query_execution_log(
        self,
        *,
        canonical_id: str | None = None,
        operation_type: str | None = None,
        limit: int | None = None,
    ) -> tuple[ExecutionLogEntry, ...]:
        """
        Return successfully checkpointed execution records.

        Results are ordered newest first. Optional filters restrict the
        returned records without inspecting canonical Archive state or
        making synchronization decisions.
        """
        raise NotImplementedError

