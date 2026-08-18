from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from archive_sync_engine.archive import Archive, ArchivePaths, ArchiveWriter
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
