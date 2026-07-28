"""
SQLite schema definition for Archive Packages.

ArchiveSchema owns the canonical SQLite schema used by Archive Packages.

It is responsible for:

    * Creating new archive databases.
    * Validating existing archive databases.
    * Managing schema versioning.
"""

from __future__ import annotations

import sqlite3


class ArchiveSchema:
    """
    Canonical Archive Package database schema.
    """

    SCHEMA_VERSION = 1

    @classmethod
    def create(
        cls,
        connection: sqlite3.Connection,
    ) -> None:
        """
        Create a new archive database.
        """

        cls._execute_schema(connection)

        connection.execute(
            """
            INSERT INTO archive_metadata
            (
                key,
                value
            )
            VALUES
            (
                'schema_version',
                ?
            )
            """,
            (
                str(cls.SCHEMA_VERSION),
            ),
        )

        connection.commit()

    @classmethod
    def validate(
        cls,
        connection: sqlite3.Connection,
    ) -> None:
        """
        Validate an existing archive database.
        """

        row = connection.execute(
            """
            SELECT value

            FROM archive_metadata

            WHERE key = 'schema_version'
            """
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "Archive database does not contain a schema version."
            )

        version = int(row["value"])

        if version != cls.SCHEMA_VERSION:
            raise RuntimeError(
                "Unsupported archive schema version "
                f"{version}."
            )

    @staticmethod
    def _execute_schema(
        connection: sqlite3.Connection,
    ) -> None:
        """
        Create the canonical Archive Package schema.
        """

        connection.executescript(
            """
            CREATE TABLE archive_metadata
            (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE conversations
            (
                id TEXT PRIMARY KEY,

                conversation_type TEXT NOT NULL,

                title TEXT,

                created_at TEXT NOT NULL
            );
            """
        )
