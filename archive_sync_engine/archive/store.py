"""
Persistent storage for an Archive Package.

ArchiveStore owns the SQLite connection and is responsible for reading
and writing canonical archive data.

SQL is intentionally encapsulated inside this class.
"""

from __future__ import annotations

import sqlite3

from pathlib import Path

from .paths import ArchivePaths


class ArchiveStore:
    """
    SQLite-backed storage implementation for an Archive Package.
    """

    def __init__(
        self,
        paths: ArchivePaths,
    ) -> None:

        self._paths = paths

        self._connection = sqlite3.connect(
            self._paths.database,
        )

        self._connection.row_factory = sqlite3.Row

    @property
    def database_path(
        self,
    ) -> Path:
        """
        Path to the archive database.
        """

        return self._paths.database

    def commit(
        self,
    ) -> None:
        """
        Commit the current transaction.
        """

        self._connection.commit()

    def rollback(
        self,
    ) -> None:
        """
        Roll back the current transaction.
        """

        self._connection.rollback()

    def close(
        self,
    ) -> None:
        """
        Close the archive database.
        """

        self._connection.close()