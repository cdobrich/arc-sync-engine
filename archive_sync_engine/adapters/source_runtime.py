"""Runtime boundary for source-platform imports.

A source runtime owns platform-specific client/session lifecycle and exposes
its canonical ``SourceAdapter`` to the application import workflow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.adapters.source import SourceAdapter
from archive_sync_engine.importer.canonical_coordinator import ImportReport


class SourceImportRuntime(ABC):
    """Platform runtime capable of importing through a ``SourceAdapter``."""

    adapter: SourceAdapter
    input_scope: tuple[str, ...] = ()

    @abstractmethod
    def import_to_archive(
        self,
        archive_paths: ArchivePaths,
        *,
        resume: bool = False,
    ) -> ImportReport:
        """Import the runtime's source into the supplied Archive Package.

        The returned report describes canonical Archive contents after the
        import.  Concrete runtimes must not reinterpret the report.
        """
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Release platform-specific resources owned by the runtime."""
        raise NotImplementedError

    def __enter__(self) -> "SourceImportRuntime":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
