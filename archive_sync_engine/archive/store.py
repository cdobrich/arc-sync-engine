"""
Persistent storage for an Archive Package.

ArchiveStore owns the SQLite connection and encapsulates all database
access for Archive Packages.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from archive_sync_engine.models import CanonicalConversation, CanonicalMessage
from archive_sync_engine.models.identity import CanonicalIdentity
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.ids import ConversationId, IdentityKey, MessageId

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
    # Conversations
    #

    @staticmethod
    def _conversation_parameters(
            conversation: CanonicalConversation,
    ) -> tuple[
        str,
        str,
        str | None,
        str | None,
        str | None,
    ]:
        """
        Convert a CanonicalConversation into SQL parameters.
        """

        return (
            str(conversation.id),
            conversation.conversation_type.value,
            conversation.title,
            (
                str(conversation.parent_id)
                if conversation.parent_id is not None
                else None
            ),
            (
                conversation.created_at.isoformat()
                if conversation.created_at is not None
                else None
            ),
        )

    @staticmethod
    def _row_to_conversation(
            row: sqlite3.Row,
    ) -> CanonicalConversation:
        """
        Convert a SQLite row into a CanonicalConversation.
        """

        return CanonicalConversation(
            id=ConversationId(
                row["conversation_id"],
            ),
            conversation_type=ConversationType(
                row["conversation_type"],
            ),
            title=row["title"],
            parent_id=(
                ConversationId(
                    row["parent_id"],
                )
                if row["parent_id"] is not None
                else None
            ),
            created_at=(
                datetime.fromisoformat(
                    row["created_at"],
                )
                if row["created_at"] is not None
                else None
            ),
        )

    def insert_conversation(
            self,
            conversation: CanonicalConversation,
    ) -> None:
        """
        Persist a CanonicalConversation.
        """

        self._connection.execute(
            """
            INSERT INTO conversations (
                conversation_id,
                conversation_type,
                title,
                parent_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            self._conversation_parameters(
                conversation,
            ),
        )

    def get_conversation(
            self,
            conversation_id: ConversationId,
    ) -> CanonicalConversation | None:
        """
        Retrieve a canonical conversation.
        """

        cursor = self._connection.execute(
            """
            SELECT
                conversation_id,
                conversation_type,
                title,
                parent_id,
                created_at
            FROM conversations
            WHERE conversation_id = ?
            """,
            (
                str(conversation_id),
            ),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_conversation(
            row,
        )

    def iter_conversations(
            self,
    ) -> Iterator[
        CanonicalConversation
    ]:
        """
        Iterate over every canonical conversation.
        """

        cursor = self._connection.execute(
            """
            SELECT
                conversation_id,
                conversation_type,
                title,
                parent_id,
                created_at
            FROM conversations
            ORDER BY
                created_at,
                conversation_id
            """
        )

        for row in cursor:
            yield self._row_to_conversation(
                row,
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

    #
    # Messages
    #

    def insert_message(
            self,
            message: CanonicalMessage,
    ) -> None:
        """
        Persist a canonical message.
        """

        self._connection.execute(
            """
            INSERT INTO messages (
                message_id,
                conversation_id,
                identity_key,
                created_at,
                edited_at,
                reply_to_message_id,
                content
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            self._message_parameters(
                message,
            ),
        )

    def get_message(
            self,
            message_id: MessageId,
    ) -> CanonicalMessage | None:
        """
        Retrieve a canonical message.
        """

        cursor = self._connection.execute(
            """
            SELECT
                message_id,
                conversation_id,
                identity_key,
                created_at,
                edited_at,
                reply_to_message_id,
                content
            FROM messages
            WHERE message_id = ?
            """,
            (
                str(message_id),
            ),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_message(
            row,
        )

    def iter_messages(
            self,
    ) -> Iterator[
        CanonicalMessage
    ]:
        """
        Iterate over every canonical message.
        """

        cursor = self._connection.execute(
            """
            SELECT
                message_id,
                conversation_id,
                identity_key,
                created_at,
                edited_at,
                reply_to_message_id,
                content
            FROM messages
            ORDER BY
                created_at,
                message_id
            """
        )

        for row in cursor:
            yield self._row_to_message(
                row,
            )

    #
    # Message mapping
    #

    @staticmethod
    def _message_parameters(
        message: CanonicalMessage,
    ) -> tuple[
        str,
        str,
        str,
        str,
        str | None,
        str | None,
        str | None,
    ]:

        return (
            str(message.id),
            str(message.conversation_id),
            str(message.identity_key),
            message.created_at.isoformat(),
            (
                message.edited_at.isoformat()
                if message.edited_at is not None
                else None
            ),
            (
                str(message.reply_to)
                if message.reply_to is not None
                else None
            ),
            message.content,
        )

    @staticmethod
    def _row_to_message(
        row: sqlite3.Row,
    ) -> CanonicalMessage:

        return CanonicalMessage(
            id=MessageId(row["message_id"]),
            conversation_id=ConversationId(
                row["conversation_id"],
            ),
            identity_key=IdentityKey(
                row["identity_key"],
            ),
            created_at=datetime.fromisoformat(
                row["created_at"],
            ),
            edited_at=(
                datetime.fromisoformat(
                row["edited_at"],
            )
            if row["edited_at"] is not None
            else None
        ),
        reply_to=(
            MessageId(
                row["reply_to_message_id"],
            )
            if row["reply_to_message_id"] is not None
            else None
        ),
        content=row["content"],
        attachments=(),
        reactions=(),
    )