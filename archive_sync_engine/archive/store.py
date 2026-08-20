"""
Persistent storage for an Archive Package.

ArchiveStore owns the SQLite connection and encapsulates all database
access for Archive Packages.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import sqlite3

from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalMessage,
    CanonicalCustomEmoji,
    CanonicalReaction,
)
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.identity import CanonicalIdentity
from archive_sync_engine.models.ids import (
    AttachmentId,
    ConversationId,
    EmojiId,
    IdentityKey,
    MessageId,
)
from archive_sync_engine.models.provenance import (
    CanonicalEndpoint,
    CanonicalTransfer,
)

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
    # Custom emojis
    #

    @staticmethod
    def _custom_emoji_parameters(emoji: CanonicalCustomEmoji) -> tuple[object, ...]:
        return (
            str(emoji.id),
            emoji.name,
            int(emoji.animated),
            emoji.content_type,
            emoji.size,
            emoji.sha256,
        )

    def insert_custom_emoji(self, emoji: CanonicalCustomEmoji) -> None:
        self._connection.execute(
            """
            INSERT INTO custom_emojis
                (emoji_id, name, animated, content_type, size, sha256)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            self._custom_emoji_parameters(emoji),
        )

    def upsert_custom_emoji(self, emoji: CanonicalCustomEmoji) -> None:
        self._connection.execute(
            """
            INSERT INTO custom_emojis
                (emoji_id, name, animated, content_type, size, sha256)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(emoji_id) DO UPDATE SET
                name = excluded.name,
                animated = excluded.animated,
                content_type = excluded.content_type,
                size = excluded.size,
                sha256 = excluded.sha256
            """,
            self._custom_emoji_parameters(emoji),
        )

    @staticmethod
    def _row_to_custom_emoji(row: sqlite3.Row) -> CanonicalCustomEmoji:
        return CanonicalCustomEmoji(
            id=EmojiId(row["emoji_id"]),
            name=row["name"],
            animated=bool(row["animated"]),
            content_type=row["content_type"],
            size=int(row["size"]),
            sha256=row["sha256"],
        )

    def iter_custom_emojis(self) -> Iterator[CanonicalCustomEmoji]:
        rows = self._connection.execute(
            "SELECT emoji_id, name, animated, content_type, size, sha256 FROM custom_emojis ORDER BY emoji_id"
        )
        for row in rows:
            yield self._row_to_custom_emoji(row)

    def get_custom_emoji(self, emoji_id: EmojiId) -> CanonicalCustomEmoji | None:
        row = self._connection.execute(
            "SELECT emoji_id, name, animated, content_type, size, sha256 FROM custom_emojis WHERE emoji_id = ?",
            (str(emoji_id),),
        ).fetchone()
        return None if row is None else self._row_to_custom_emoji(row)

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

    def upsert_attachment(
        self,
        attachment: CanonicalAttachment,
    ) -> None:
        """Insert attachment metadata or refresh it by stable attachment ID."""
        self._connection.execute(
            """
            INSERT INTO attachments (attachment_id, filename, content_type, size, sha256)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(attachment_id) DO UPDATE SET
                filename = excluded.filename,
                content_type = excluded.content_type,
                size = excluded.size,
                sha256 = excluded.sha256
            """,
            self._attachment_parameters(attachment),
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
    ) -> Iterator[CanonicalAttachment]:
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
    # Message Attachments and Attachment Relationships
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

    def upsert_conversation(
        self,
        conversation: CanonicalConversation,
    ) -> None:
        """Insert a conversation or refresh its current canonical representation."""
        self._connection.execute(
            """
            INSERT INTO conversations (
                conversation_id, conversation_type, title, parent_id, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                conversation_type = excluded.conversation_type,
                title = excluded.title,
                parent_id = excluded.parent_id,
                created_at = excluded.created_at
            """,
            self._conversation_parameters(conversation),
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
    ) -> Iterator[CanonicalConversation]:
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

    def iter_messages_for_conversation(
        self,
        conversation_id: ConversationId,
    ) -> Iterator[CanonicalMessage]:
        """
        Iterate over messages belonging to a conversation in
        deterministic chronological order.
        """

        rows = self._connection.execute(
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
            WHERE conversation_id = ?
            ORDER BY
                created_at,
                message_id
            """,
            (
                str(conversation_id),
            ),
        )

        for row in rows:
            yield self._row_to_message(
                row,
            )

    #
    # Identity Mapping
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
            self._identity_parameters(
                identity,
            ),
        )

    def upsert_identity(
        self,
        identity: CanonicalIdentity,
    ) -> None:
        """Insert an identity or refresh its current canonical representation."""
        self._connection.execute(
            """
            INSERT INTO identities (identity_key, display_name)
            VALUES (?, ?)
            ON CONFLICT(identity_key) DO UPDATE SET
                display_name = excluded.display_name
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
            (
                identity_key,
            ),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_identity(
            row,
        )

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
            ORDER BY
                identity_key
            """
        )

        for row in cursor:
            yield self._row_to_identity(
                row,
            )

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

    def upsert_message(
        self,
        message: CanonicalMessage,
    ) -> None:
        """Insert a message or replace its mutable aggregate state."""
        self._connection.execute(
            """
            INSERT INTO messages (
                message_id, conversation_id, identity_key, created_at,
                edited_at, reply_to_message_id, content
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                conversation_id = excluded.conversation_id,
                identity_key = excluded.identity_key,
                created_at = excluded.created_at,
                edited_at = excluded.edited_at,
                reply_to_message_id = excluded.reply_to_message_id,
                content = excluded.content
            """,
            self._message_parameters(message),
        )

        self._connection.execute(
            "DELETE FROM message_attachments WHERE message_id = ?",
            (str(message.id),),
        )
        self._connection.execute(
            "DELETE FROM message_reactions WHERE message_id = ?",
            (str(message.id),),
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
    ) -> Iterator[CanonicalMessage]:
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
    # Message Mapping
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
        """
        Convert a CanonicalMessage into SQL parameters.
        """

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

    def _row_to_message(
        self,
        row: sqlite3.Row,
    ) -> CanonicalMessage:
        """
        Convert a SQLite row into a complete CanonicalMessage aggregate.

        Message attachments are stored in normalized tables rather than
        duplicated in the message row.  They must therefore be rehydrated
        before constructing ``CanonicalMessage``.  In particular, an
        attachment-only message has empty text but is still a valid canonical
        message; constructing the row with ``attachments=()`` would violate
        the canonical message invariant and make archive reads fail after a
        successful import.
        """

        message_id = MessageId(row["message_id"])

        return CanonicalMessage(
            id=message_id,
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
            attachments=tuple(self.attachments_for_message(message_id)),
            reactions=tuple(self.reactions_for_message(message_id)),
        )

    #
    # Message Reactions
    #

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

    #
    # Provenance
    #

    @staticmethod
    def _provenance_endpoint_parameters(
        endpoint: CanonicalEndpoint,
    ) -> tuple[
        str,
        str,
        str | None,
    ]:
        """
        Convert a CanonicalEndpoint into SQL parameters.
        """

        return (
            endpoint.adapter,
            endpoint.identifier,
            endpoint.name,
        )

    @staticmethod
    def _row_to_provenance_endpoint(
        row: sqlite3.Row,
    ) -> CanonicalEndpoint:
        """
        Convert a SQLite row into a CanonicalEndpoint.
        """

        return CanonicalEndpoint(
            adapter=row["adapter"],
            identifier=row["identifier"],
            name=row["name"],
        )

    def insert_provenance_endpoint(
        self,
        endpoint: CanonicalEndpoint,
    ) -> None:
        """
        Persist a canonical provenance endpoint.

        Endpoint identity is defined by its adapter and identifier.
        """

        self._connection.execute(
            """
            INSERT INTO provenance_endpoints (
                adapter,
                identifier,
                name
            )
            VALUES (?, ?, ?)
            ON CONFLICT (
                adapter,
                identifier
            )
            DO UPDATE SET
                name = excluded.name
            """,
            self._provenance_endpoint_parameters(
                endpoint,
            ),
        )

    def get_provenance_endpoint(
        self,
        adapter: str,
        identifier: str,
    ) -> CanonicalEndpoint | None:
        """
        Retrieve a provenance endpoint by adapter and identifier.
        """

        cursor = self._connection.execute(
            """
            SELECT
                adapter,
                identifier,
                name
            FROM provenance_endpoints
            WHERE adapter = ?
              AND identifier = ?
            """,
            (
                adapter,
                identifier,
            ),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_provenance_endpoint(
            row,
        )

    def iter_provenance_endpoints(
        self,
    ) -> Iterator[CanonicalEndpoint]:
        """
        Iterate over every canonical provenance endpoint.
        """

        cursor = self._connection.execute(
            """
            SELECT
                adapter,
                identifier,
                name
            FROM provenance_endpoints
            ORDER BY
                adapter,
                identifier
            """
        )

        for row in cursor:
            yield self._row_to_provenance_endpoint(
                row,
            )

    def _provenance_endpoint_id(
        self,
        endpoint: CanonicalEndpoint,
    ) -> int:
        """
        Retrieve the SQLite identifier for a provenance endpoint.

        The SQLite identifier is an internal persistence detail and is
        never exposed through the canonical model.
        """

        row = self._connection.execute(
            """
            SELECT endpoint_id
            FROM provenance_endpoints
            WHERE adapter = ?
              AND identifier = ?
            """,
            (
                endpoint.adapter,
                endpoint.identifier,
            ),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "Provenance endpoint was not found after insertion."
            )

        return int(
            row["endpoint_id"],
        )

    @staticmethod
    def _provenance_transfer_parameters(
        transfer: CanonicalTransfer,
        source_endpoint_id: int,
        destination_endpoint_id: int | None,
    ) -> tuple[
        int,
        int | None,
        str,
        str | None,
        int,
        int,
    ]:
        """
        Convert a CanonicalTransfer into SQL parameters.
        """

        return (
            source_endpoint_id,
            destination_endpoint_id,
            transfer.started_at.isoformat(),
            (
                transfer.finished_at.isoformat()
                if transfer.finished_at is not None
                else None
            ),
            transfer.imported_messages,
            transfer.exported_messages,
        )

    @staticmethod
    def _row_to_provenance_transfer(
        row: sqlite3.Row,
    ) -> CanonicalTransfer:
        """
        Convert a SQLite row into a CanonicalTransfer.
        """

        source = CanonicalEndpoint(
            adapter=row["source_adapter"],
            identifier=row["source_identifier"],
            name=row["source_name"],
        )

        destination = None

        if row["destination_endpoint_id"] is not None:
            destination = CanonicalEndpoint(
                adapter=row["destination_adapter"],
                identifier=row["destination_identifier"],
                name=row["destination_name"],
            )

        return CanonicalTransfer(
            source=source,
            destination=destination,
            started_at=datetime.fromisoformat(
                row["started_at"],
            ),
            finished_at=(
                datetime.fromisoformat(
                    row["finished_at"],
                )
                if row["finished_at"] is not None
                else None
            ),
            imported_messages=row["imported_messages"],
            exported_messages=row["exported_messages"],
        )

    def insert_provenance_transfer(
        self,
        transfer: CanonicalTransfer,
    ) -> None:
        """
        Persist a canonical provenance transfer.
        """

        self.insert_provenance_endpoint(
            transfer.source,
        )

        source_endpoint_id = self._provenance_endpoint_id(
            transfer.source,
        )

        destination_endpoint_id = None

        if transfer.destination is not None:

            self.insert_provenance_endpoint(
                transfer.destination,
            )

            destination_endpoint_id = (
                self._provenance_endpoint_id(
                    transfer.destination,
                )
            )

        self._connection.execute(
            """
            INSERT INTO provenance_transfers (
                source_endpoint_id,
                destination_endpoint_id,
                started_at,
                finished_at,
                imported_messages,
                exported_messages
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            self._provenance_transfer_parameters(
                transfer,
                source_endpoint_id,
                destination_endpoint_id,
            ),
        )

    def iter_provenance_transfers(
        self,
    ) -> Iterator[CanonicalTransfer]:
        """
        Iterate over every canonical provenance transfer in historical order.
        """

        cursor = self._connection.execute(
            """
            SELECT
                pt.source_endpoint_id,
                pt.destination_endpoint_id,
                pt.started_at,
                pt.finished_at,
                pt.imported_messages,
                pt.exported_messages,

                source.adapter AS source_adapter,
                source.identifier AS source_identifier,
                source.name AS source_name,

                destination.adapter AS destination_adapter,
                destination.identifier AS destination_identifier,
                destination.name AS destination_name

            FROM provenance_transfers AS pt

            INNER JOIN provenance_endpoints AS source
                ON source.endpoint_id = pt.source_endpoint_id

            LEFT JOIN provenance_endpoints AS destination
                ON destination.endpoint_id =
                    pt.destination_endpoint_id

            ORDER BY
                pt.started_at,
                pt.transfer_id
            """
        )

        for row in cursor:
            yield self._row_to_provenance_transfer(
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

    def close(
        self,
    ) -> None:
        self._connection.close()

