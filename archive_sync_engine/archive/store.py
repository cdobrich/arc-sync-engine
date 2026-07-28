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

    def commit(
        self,
    ) -> None:
        """
        Commit the current SQLite transaction.
        """

        self._connection.commit()


    def rollback(
        self,
    ) -> None:
        """
        Roll back the current SQLite transaction.
        """

        self._connection.rollback()

    #
    # Lifecycle
    #

    def close(self) -> None:
        self._connection.close()

    #
    # Identity mapping
    #

    @staticmethod
    def _identity_parameters(
        identity: CanonicalIdentity,
    ) -> tuple[str, str]:
        """
        Convert a CanonicalIdentity into SQL parameters.
        """

        return (
            identity.key,
            identity.display_name,
        )


    @staticmethod
    def _row_to_identity(
        row: sqlite3.Row,
    ) -> CanonicalIdentity:
        """
        Convert a SQLite row into a CanonicalIdentity.
        """

        return CanonicalIdentity(
            key=row["identity_key"],
            display_name=row["display_name"],
        )
    
    def insert_identity(
        self,
        identity: CanonicalIdentity,
    ) -> None:
        """
        Persist a CanonicalIdentity.
        """

        self._connection.execute(
            """
            INSERT INTO identities (
                identity_key,
                display_name
            )
            VALUES (?, ?)
            """,
            self._identity_parameters(identity),
        )
    
    def get_identity(
        self,
        identity_key: IdentityKey,
    ) -> CanonicalIdentity | None:
        """
        Retrieve an identity by its canonical key.
        """

        cursor = self._connection.execute(
            """
            SELECT
                identity_key,
                display_name
            FROM identities
            WHERE identity_key = ?
            """,
            (identity_key,),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_identity(row)

    def iter_identities(
        self,
    ) -> Iterator[CanonicalIdentity]:
        """
        Iterate over every identity.
        """

        cursor = self._connection.execute(
            """
            SELECT
                identity_key,
                display_name
            FROM identities
            ORDER BY identity_key
            """
        )

        for row in cursor:
            yield self._row_to_identity(row)





