"""
Persistent storage for an Archive Package.

ArchiveStore owns the SQLite connection and encapsulates all database
access for Archive Packages.
"""

from __future__ import annotations

from datetime import datetime

from archive_sync_engine.models import CanonicalConversation
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.ids import ConversationId

import sqlite3

from .paths import ArchivePaths
from .schema import ArchiveSchema


class ArchiveStore:
    """
    SQLite-backed storage implementation for an Archive Package.
    """

    def __init__(
        self,
        paths: ArchivePaths,
        connection: sqlite3.Connection,
    ) -> None:
        self._paths = paths
        self._connection = connection

        self._connection.row_factory = sqlite3.Row

    #
    # Construction
    #

    @classmethod
    def create(
        cls,
        paths: ArchivePaths,
    ) -> "ArchiveStore":
        """
        Create a new archive database.

        Any existing database file is considered an error.
        """

        connection = sqlite3.connect(paths.database)
        connection.row_factory = sqlite3.Row

        ArchiveSchema.create(connection)

        return cls(
            paths=paths,
            connection=connection,
        )

    @classmethod
    def open(
        cls,
        paths: ArchivePaths,
    ) -> "ArchiveStore":
        """
        Open an existing archive database.
        """

        connection = sqlite3.connect(paths.database)
        connection.row_factory = sqlite3.Row

        ArchiveSchema.validate(connection)

        return cls(
            paths=paths,
            connection=connection,
        )

    #
    # Transactions
    #

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    #
    # Lifecycle
    #

    def close(self) -> None:
        self._connection.close()
