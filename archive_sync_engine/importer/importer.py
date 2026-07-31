"""
Importer interface.

An Importer performs the mechanics of importing canonical data from a
SourceAdapter into an Archive Package.

Importers do not own import sessions, checkpointing, retry behaviour,
or pause/resume functionality. Those responsibilities belong to the
ImportCoordinator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from archive_sync_engine.adapters import SourceAdapter
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.asset_store import AssetStore


class Importer(ABC):
    """
    Performs canonical data acquisition from a SourceAdapter.
    """

    @abstractmethod
    def import_source(
        self,
        source: SourceAdapter,
        writer: ArchiveWriter,
        asset_store: AssetStore,
    ) -> None:
        """
        Import canonical information from the source.

        Implementations translate platform-specific source data into
        canonical models and persist those models through ArchiveWriter.

        Asset bytes are persisted through AssetStore.

        Session lifecycle, checkpointing, retries, and progress reporting
        remain the responsibility of ImportCoordinator.
        """
        raise NotImplementedError