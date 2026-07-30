"""
Persistent storage for an Archive Package.

ArchiveStore owns the SQLite connection and encapsulates all database
access for Archive Packages.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from archive_sync_engine.models import CanonicalConversation, CanonicalMessage, CanonicalAttachment, CanonicalReaction
from archive_sync_engine.models.identity import CanonicalIdentity
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.ids import ConversationId, IdentityKey, MessageId, AttachmentId, EmojiId

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
    # Attachments
    #

    @staticmethod
    def _attachment_parameters(
            attachment: CanonicalAttachment,
    ) -> tuple[
        str,
        str,
        str | None,
        int,
        str,
    ]:
        """
        Convert a CanonicalAttachment into SQL parameters.
        """

        return (
            str(attachment.id),
            attachment.filename,
            attachment.content_type,
            attachment.size,
            attachment.sha256,
        )

    @staticmethod
    def _row_to_attachment(
            row: sqlite3.Row,
    ) -> CanonicalAttachment:
        """
        Convert a SQLite row into a CanonicalAttachment.
        """

        return CanonicalAttachment(
            id=AttachmentId(
                row["attachment_id"],
            ),
            filename=row["filename"],
            content_type=row["content_type"],
            size=row["size"],
            sha256=row["sha256"],
        )

    def insert_attachment(
            self,
            attachment: CanonicalAttachment,
    ) -> None:
        """
        Persist a canonical attachment.
        """

        self._connection.execute(
            """
            INSERT INTO attachments (
                attachment_id,
                filename,
                content_type,
                size,
                sha256
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            self._attachment_parameters(
                attachment,
            ),
        )

    def get_attachment(
            self,
            attachment_id: AttachmentId,
    ) -> CanonicalAttachment | None:
        """
        Retrieve a canonical attachment.
        """

        cursor = self._connection.execute(
            """
            SELECT
                attachment_id,
                filename,
                content_type,
                size,
                sha256
            FROM attachments
            WHERE attachment_id = ?
            """,
            (
                str(attachment_id),
            ),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_attachment(
            row,
        )

    def iter_attachments(
            self,
    ) -> Iterator[
        CanonicalAttachment
    ]:
        """
        Iterate over every canonical attachment.
        """

        cursor = self._connection.execute(
            """
            SELECT
                attachment_id,
                filename,
                content_type,
                size,
                sha256
            FROM attachments
            ORDER BY
                attachment_id
            """
        )

        for row in cursor:
            yield self._row_to_attachment(
                row,
            )

    #
    # Message Attachments and Attachments Relationships
    #

    def attachments_for_message(
            self,
            message_id: MessageId,
    ) -> Iterator[CanonicalAttachment]:
        """
        Iterate over every attachment belonging to a message.
        """

        cursor = self._connection.execute(
            """
            SELECT
                a.attachment_id,
                a.filename,
                a.content_type,
                a.size,
                a.sha256
            FROM attachments AS a
            INNER JOIN message_attachments AS ma
                ON a.attachment_id = ma.attachment_id
            WHERE ma.message_id = ?
            ORDER BY
                ma.attachment_index
            """,
            (
                str(message_id),
            ),
        )

        for row in cursor:
            yield self._row_to_attachment(
                row,
            )

    def insert_message_attachment(
            self,
            message_id: MessageId,
            attachment_id: AttachmentId,
            attachment_index: int,
    ) -> None:
        """
        Persist a message/attachment relationship.
        """

        if attachment_index < 0:
            raise ValueError(
                "attachment_index must be non-negative."
            )

        self._connection.execute(
            """
            INSERT INTO message_attachments (
                message_id,
                attachment_id,
                attachment_index
            )
            VALUES (?, ?, ?)
            """,
            (
                str(message_id),
                str(attachment_id),
                attachment_index,
            ),
        )

    def messages_for_attachment(
            self,
            attachment_id: AttachmentId,
    ) -> Iterator[MessageId]:
        """
        Iterate over every message referencing an attachment.
        """

        cursor = self._connection.execute(
            """
            SELECT
                message_id
            FROM message_attachments
            WHERE attachment_id = ?
            ORDER BY
                message_id
            """,
            (
                str(attachment_id),
            ),
        )

        for row in cursor:
            yield MessageId(
                row["message_id"],
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
            identity.identity_key,
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
            identity_key=row["identity_key"],
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
        Retrieve a canonical message (the message core).
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

    def _message_reaction_parameters(
            self,
            message_id: MessageId,
            reaction: CanonicalReaction,
    ) -> tuple[object, ...]:
        """
        Convert a CanonicalReaction into database parameters.
        """

        return (
            str(message_id),
            str(reaction.identity_key),
            reaction.emoji,
            (
                None
                if reaction.emoji_id is None
                else str(reaction.emoji_id)
            ),
            int(reaction.is_custom),
        )

    def _row_to_message_reaction(
            self,
            row: sqlite3.Row,
    ) -> CanonicalReaction:
        """
        Convert a database row into a CanonicalReaction.
        """

        return CanonicalReaction(
            identity_key=IdentityKey(
                row["identity_key"],
            ),
            emoji=row["emoji"],
            emoji_id=(
                None
                if row["emoji_id"] is None
                else EmojiId(
                    row["emoji_id"],
                )
            ),
            is_custom=bool(
                row["is_custom"],
            ),
        )

    def insert_message_reaction(
            self,
            message_id: MessageId,
            reaction: CanonicalReaction,
    ) -> None:
        """
        Persist a reaction belonging to a message.
        """

        self._connection.execute(
            """
            INSERT INTO message_reactions (
                message_id,
                identity_key,
                emoji,
                emoji_id,
                is_custom
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            self._message_reaction_parameters(
                message_id,
                reaction,
            ),
        )

    def reactions_for_message(
            self,
            message_id: MessageId,
    ) -> Iterator[CanonicalReaction]:
        """
        Iterate over reactions belonging to a message.
        """

        cursor = self._connection.execute(
            """
            SELECT
                identity_key,
                emoji,
                emoji_id,
                is_custom
            FROM message_reactions
            WHERE message_id = ?
            ORDER BY
                identity_key,
                emoji,
                emoji_id
            """,
            (
                str(message_id),
            ),
        )

        for row in cursor:
            yield self._row_to_message_reaction(
                row,
            )

    def delete_message_reactions(
            self,
            message_id: MessageId,
    ) -> None:
        """
        Remove all reactions belonging to a message.
        """

        self._connection.execute(
            """
            DELETE FROM message_reactions
            WHERE message_id = ?
            """,
            (
                str(message_id),
            ),
        )