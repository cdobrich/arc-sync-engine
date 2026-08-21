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

from collections.abc import Callable
from dataclasses import dataclass

from archive_sync_engine.adapters import DestinationAdapter
from archive_sync_engine.archive import Archive
from archive_sync_engine.asset_store import AssetStore
from archive_sync_engine.executor import OperationExecutor
from archive_sync_engine.planner import Planner
from archive_sync_engine.repository import InMemoryStateRepository, StateRepository
from archive_sync_engine.sync.coordinator import SyncCoordinator
from archive_sync_engine.sync.progress import SyncProgress


@dataclass(frozen=True, slots=True)
class ExportReport:
    """Summary of one completed Archive export."""

    executed_operations: int
    skipped_operations: int = 0


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
        on_status: Callable[[SyncProgress], None] | None = None,
        between_messages_seconds: float = 0.0,
        between_channels_seconds: float = 0.0,
        state_repository: StateRepository | None = None,
        compatibility_mode: bool = False,
    ) -> ExportReport:
        """
        Reproduce the canonical Archive at the destination.

        The synchronization state repository determines whether this is an
        initial export or a subsequent reconciliation. Callers that need
        repeatable exports must provide a durable StateRepository so destination
        references survive between CLI invocations.

        When no repository is supplied, a fresh in-memory repository is used
        for callers that intentionally want one-shot export semantics.
        """
        capabilities = destination.capabilities
        repository = state_repository or InMemoryStateRepository()
        executor = OperationExecutor(
            asset_store=asset_store,
        )

        coordinator = SyncCoordinator(
            archive=archive,
            planner=Planner(),
            executor=executor,
            destination=destination,
            capabilities=capabilities,
            state_repository=repository,
            on_status=on_status,
            between_messages_seconds=between_messages_seconds,
            between_channels_seconds=between_channels_seconds,
            compatibility_mode=compatibility_mode,
        )

        results = coordinator.synchronize()
        skipped = sum(1 for result in results if result.skipped)
        return ExportReport(
            executed_operations=len(results) - skipped,
            skipped_operations=skipped,
        )
