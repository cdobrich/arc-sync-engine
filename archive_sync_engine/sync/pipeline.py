"""Archive-mediated source-to-destination synchronization pipeline."""
from __future__ import annotations

from pathlib import Path

from archive_sync_engine.adapters import DestinationAdapter, SourceAdapter
from archive_sync_engine.archive import Archive, ArchivePaths
from archive_sync_engine.executor import OperationExecutor
from archive_sync_engine.importer.canonical_coordinator import (
    CanonicalImportCoordinator,
)
from archive_sync_engine.planner import Planner
from archive_sync_engine.asset_store import AssetStore
from archive_sync_engine.repository import InMemoryStateRepository, SQLiteStateRepository
from archive_sync_engine.operations import SyncOperation

from .coordinator import SyncCoordinator


class ArchiveSyncPipeline:
    """Run a source import followed by synchronization from the Archive.

    The pipeline is an application-level orchestration boundary. It does not
    inspect canonical entities or implement synchronization decisions. Import
    and export remain owned by their existing coordinators.
    """

    def __init__(
        self,
        *,
        archive_paths: ArchivePaths,
        state_repository_path: str | Path | None = None,
    ) -> None:
        self._archive_paths = archive_paths
        self._state_repository_path = (
            Path(state_repository_path)
            if state_repository_path is not None
            else archive_paths.root / "synchronization.sqlite"
        )

    def dry_run(
        self,
        *,
        destination: DestinationAdapter,
    ) -> tuple[SyncOperation, ...]:
        """Plan synchronization without importing, executing, or persisting.

        The canonical Archive is read as-is. The destination adapter supplies
        capabilities only; no destination operation is executed.
        """
        from archive_sync_engine.operations import SyncOperation

        with Archive(self._archive_paths) as archive:
            if Path(self._state_repository_path).is_file():
                with SQLiteStateRepository(
                    self._state_repository_path,
                ) as state_repository:
                    return SyncCoordinator(
                        archive=archive,
                        planner=Planner(),
                        executor=OperationExecutor(
                            asset_store=AssetStore(self._archive_paths.root),
                        ),
                        destination=destination,
                        capabilities=destination.capabilities,
                        state_repository=state_repository,
                    ).dry_run()

            return SyncCoordinator(
                archive=archive,
                planner=Planner(),
                executor=OperationExecutor(
                    asset_store=AssetStore(self._archive_paths.root),
                ),
                destination=destination,
                capabilities=destination.capabilities,
                state_repository=InMemoryStateRepository(),
            ).dry_run()

    def run(
        self,
        *,
        source: SourceAdapter,
        destination: DestinationAdapter,
        resume_import: bool = False,
    ) -> None:
        """Import ``source`` into the Archive, then synchronize it.

        Import must complete successfully before the destination is touched.
        The destination synchronization uses a durable SQLite StateRepository
        located alongside the Archive Package unless an explicit path was
        supplied at construction time.
        """
        CanonicalImportCoordinator(self._archive_paths).run(
            source,
            resume=resume_import,
        )

        with Archive(self._archive_paths) as archive:
            with SQLiteStateRepository(
                self._state_repository_path,
            ) as state_repository:
                SyncCoordinator(
                    archive=archive,
                    planner=Planner(),
                    executor=OperationExecutor(
                        asset_store=AssetStore(self._archive_paths.root),
                    ),
                    destination=destination,
                    capabilities=destination.capabilities,
                    state_repository=state_repository,
                ).synchronize()

