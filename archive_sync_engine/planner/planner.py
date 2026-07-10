from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from archive_sync_engine.archive import Archive
from archive_sync_engine.adapters import DestinationCapabilities
from archive_sync_engine.operations import SyncOperation
from archive_sync_engine.sync import SynchronizationState


class Planner(ABC):
    """
    Produces synchronization operations.

    The Planner owns synchronization ordering.

    Given the same Archive, SynchronizationState, and
    DestinationCapabilities, the Planner must produce the same ordered
    stream of SyncOperations.
    """

    @abstractmethod
    def plan(
        self,
        archive: Archive,
        synchronization_state: SynchronizationState,
        capabilities: DestinationCapabilities,
    ) -> Iterator[SyncOperation]:
        """
        Produce a dependency-safe stream of synchronization operations.
        """
        raise NotImplementedError
