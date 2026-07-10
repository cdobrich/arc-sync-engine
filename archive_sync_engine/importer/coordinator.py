"""
Import session coordinator.

The ImportCoordinator owns the lifecycle of an import session.

Responsibilities include:

- starting an import
- pausing an import
- resuming an import
- checkpointing progress
- retrying failed operations
- reporting progress

The coordinator delegates the actual import work to an Importer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from archive_sync_engine.adapters import SourceAdapter

from .importer import Importer


class ImportCoordinator(ABC):
    """
    Coordinates a complete import session.
    """

    @abstractmethod
    def run(
        self,
        importer: Importer,
        source: SourceAdapter,
    ) -> None:
        """
        Execute an import session.
        """
        raise NotImplementedError

    @abstractmethod
    def pause(self) -> None:
        """
        Request that the current import session pause.
        """
        raise NotImplementedError

    @abstractmethod
    def resume(self) -> None:
        """
        Resume a previously paused import session.
        """
        raise NotImplementedError