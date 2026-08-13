"""
Canonical export facade.

CanonicalExporter exposes a convenient initial-export API while keeping the
actual synchronization lifecycle in the existing Planner/Executor/Coordinator
architecture.

The exporter does not perform destination calls directly. It supplies an
empty synchronization state and delegates the complete Archive -> Planner ->
Executor -> StateRepository flow to SyncCoordinator.
"""

from __future__ import annotations

from archive_sync_engine.adapters import DestinationAdapter
from archive_sync_engine.archive import Archive
from archive_sync_engine.asset_store import AssetStore
from archive_sync_engine.executor import OperationExecutor
from archive_sync_engine.planner import Planner
from archive_sync_engine.repository import InMemoryStateRepository
from archive_sync_engine.sync.coordinator import SyncCoordinator


class CanonicalExporter:
    """
    Export canonical archive contents through the synchronization engine.

    This is intentionally a thin public facade for callers that want a
    one-shot initial export rather than directly coordinating Planner,
    Executor, and StateRepository themselves.
    """

    def export(
        self,
        archive: Archive,
        destination: DestinationAdapter,
        asset_store: AssetStore,
    ) -> None:
        """
        Reproduce the canonical Archive at the destination.

        The export starts from an empty synchronization snapshot and lets the
        existing Planner and OperationExecutor establish destination
        references, component baselines, and dependency-safe ordering.

        A fresh in-memory StateRepository is sufficient because this facade
        represents one-shot initial export. Callers that need resumable or
        incremental synchronization should use SyncCoordinator directly with
        a durable StateRepository.
        """
        capabilities = destination.capabilities
        state_repository = InMemoryStateRepository()
        executor = OperationExecutor(
            asset_store=asset_store,
        )

        coordinator = SyncCoordinator(
            archive=archive,
            planner=Planner(),
            executor=executor,
            destination=destination,
            capabilities=capabilities,
            state_repository=state_repository,
        )

        coordinator.synchronize()
