from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from archive_sync_engine.archive import Archive, ArchivePaths, ArchiveWriter
from archive_sync_engine.archive.schema import ArchiveSchema
from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
    ConversationType,
)
from archive_sync_engine.models.ids import AttachmentId, ConversationId, IdentityKey, MessageId


def test_archive_roundtrip_rehydrates_attachment_only_message(tmp_path: Path) -> None:
    """An attachment-only message remains valid when read back from SQLite."""
    paths = ArchivePaths(tmp_path)
    content = b"attachment-only-message"
    attachment = CanonicalAttachment(
        id=AttachmentId("attachment-1"),
        filename="example.txt",
        content_type="text/plain",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    identity = CanonicalIdentity(
        identity_key=IdentityKey("discord:user:1"),
        display_name="Alice",
    )
    conversation = CanonicalConversation(
        id=ConversationId("discord:guild:1:channel:2"),
        conversation_type=ConversationType.CHANNEL,
        title="gallery-groups",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    message = CanonicalMessage(
        id=MessageId("discord:message:1"),
        conversation_id=conversation.id,
        identity_key=identity.identity_key,
        content="",
        created_at=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        attachments=(attachment,),
    )

    with ArchiveWriter(paths) as writer:
        writer.add_identity(identity)
        writer.add_conversation(conversation)
        writer.add_message(message)
        writer.commit()

    with Archive(paths) as archive:
        restored = next(archive.iter_messages())

    assert restored.id == message.id
    assert restored.content == ""
    assert restored.attachments == (attachment,)


def test_archive_roundtrip_preserves_message_pin_state(tmp_path: Path) -> None:
    """Pinned canonical intent survives the Archive SQLite round trip."""
    paths = ArchivePaths(tmp_path)
    identity = CanonicalIdentity(
        identity_key=IdentityKey("discord:user:1"),
        display_name="Alice",
    )
    conversation = CanonicalConversation(
        id=ConversationId("discord:guild:1:channel:2"),
        conversation_type=ConversationType.CHANNEL,
        title="general",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    message = CanonicalMessage(
        id=MessageId("discord:message:pinned"),
        conversation_id=conversation.id,
        identity_key=identity.identity_key,
        content="Pinned content",
        created_at=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        pinned=True,
    )

    with ArchiveWriter(paths) as writer:
        writer.add_identity(identity)
        writer.add_conversation(conversation)
        writer.add_message(message)
        writer.commit()

    with Archive(paths) as archive:
        restored = next(archive.iter_messages())

    assert restored.pinned is True


def test_archive_upsert_updates_message_pin_state(tmp_path: Path) -> None:
    """Incremental archive reconciliation persists changed pin intent."""
    paths = ArchivePaths(tmp_path)
    identity = CanonicalIdentity(
        identity_key=IdentityKey("discord:user:1"),
        display_name="Alice",
    )
    conversation = CanonicalConversation(
        id=ConversationId("discord:guild:1:channel:2"),
        conversation_type=ConversationType.CHANNEL,
        title="general",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    message = CanonicalMessage(
        id=MessageId("discord:message:mutable-pin"),
        conversation_id=conversation.id,
        identity_key=identity.identity_key,
        content="Mutable pin",
        created_at=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        pinned=False,
    )

    with ArchiveWriter(paths) as writer:
        writer.add_identity(identity)
        writer.add_conversation(conversation)
        writer.add_message(message)
        writer.commit()

    updated = CanonicalMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content=message.content,
        created_at=message.created_at,
        pinned=True,
    )
    with ArchiveWriter(paths) as writer:
        writer.upsert_message(updated)
        writer.commit()

    with Archive(paths) as archive:
        restored = next(archive.iter_messages())

    assert restored.pinned is True


def test_archive_schema_v2_migration_adds_pinned_column(tmp_path: Path) -> None:
    """Opening a current v2 archive upgrades message pin persistence."""
    database = tmp_path / "archive.sqlite"
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE archive_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE messages (
            message_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            identity_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            edited_at TEXT,
            reply_to_message_id TEXT,
            content TEXT
        );
        INSERT INTO archive_metadata(key, value) VALUES ('schema_version', '2');
        """
    )
    connection.commit()

    ArchiveSchema.validate(connection)

    columns = {row["name"] for row in connection.execute("PRAGMA table_info(messages)")}
    version = connection.execute(
        "SELECT value FROM archive_metadata WHERE key = 'schema_version'"
    ).fetchone()["value"]
    default = connection.execute(
        "SELECT dflt_value FROM pragma_table_info('messages') WHERE name = 'pinned'"
    ).fetchone()["dflt_value"]

    assert "pinned" in columns
    assert version == "3"
    assert default == "0"
    connection.close()
