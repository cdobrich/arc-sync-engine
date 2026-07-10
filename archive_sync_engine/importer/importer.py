"""
Importer interface.

An Importer performs the mechanics of importing canonical data from a
SourceAdapter into the Archive.

Importers do not own import sessions, checkpointing, retry behaviour,
or pause/resume functionality. Those responsibilities belong to the
ImportCoordinator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from archive_sync_engine.adapters import SourceAdapter
from archive_sync_engine.archive import Archive
from archive_sync_engine.asset_store import AssetStore


class Importer(ABC):
    """
    Performs canonical data acquisition from a SourceAdapter.
    """

    @abstractmethod
    def import_source(
        self,
        source: SourceAdapter,
        archive: Archive,
        asset_store: AssetStore,
    ) -> None:
        """
        Import all available canonical information from the source.

        Implementations should translate platform-specific data into
        canonical models and populate the Archive and AssetStore.

        This method performs import work only.

        Session lifecycle, checkpointing, retries, and progress reporting
        are managed by the ImportCoordinator.
        """
        raise NotImplementedError