"""
State Repository interface.

StateRepositories persist operational metadata required by the engine.

Canonical entities belong in the Archive.

State Repositories intentionally do not own canonical content.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from archive_sync_engine.importer import ImportSession


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
