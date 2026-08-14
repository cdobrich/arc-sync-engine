"""Tests for Archive-mediated source-to-destination synchronization."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from archive_sync_engine.adapters import (
    DestinationAdapter,
    DestinationConversationRef,
    DestinationMessageRef,
    DestinationCapabilities,
    SourceAdapter,
)
from archive_sync_engine.archive import ArchivePaths
from archive_sync_engine.models import CanonicalConversation, CanonicalMessage
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.ids import ConversationId, IdentityKey, MessageId
from archive_sync_engine.sync.pipeline import ArchiveSyncPipeline


def _conversation() -> CanonicalConversation:
    return CanonicalConversation(
        id=ConversationId("conversation-001"),
        conversation_type=ConversationType.CHANNEL,
        title="general",
    )


def _message() -> CanonicalMessage:
    return CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=ConversationId("conversation-001"),
        identity_key=IdentityKey("identity-001"),
        content="hello",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _source(
    conversation: CanonicalConversation | None,
    message: CanonicalMessage | None,
) -> Mock:
    source = Mock(spec=SourceAdapter)
    source.name = "test-source"
    source.iter_identities.return_value = iter(())
    source.iter_conversations.return_value = (
        iter((conversation,)) if conversation is not None else iter(())
    )
    source.iter_messages.side_effect = lambda _conversation: (
        iter((message,)) if message is not None else iter(())
    )
    source.attachment_bytes.side_effect = AssertionError(
        "attachment_bytes should not be called for this fixture"
    )
    return source


def _destination() -> Mock:
    destination = Mock(spec=DestinationAdapter)
    destination.name = "test-destination"
    destination.capabilities = DestinationCapabilities()
    destination.create_conversation.return_value = DestinationConversationRef(
        "destination-conversation-001"
    )
    destination.create_message.return_value = DestinationMessageRef(
        "destination-message-001",
        conversation_id="destination-conversation-001",
    )
    return destination


def test_archive_sync_pipeline_imports_archive_before_export(
    tmp_path: Path,
) -> None:
    source = _source(_conversation(), _message())
    destination = _destination()
    paths = ArchivePaths(tmp_path / "archive")

    ArchiveSyncPipeline(
        archive_paths=paths,
    ).run(
        source=source,
        destination=destination,
    )

    destination.create_conversation.assert_called_once()
    destination.create_message.assert_called_once()

    state_path = paths.root / "synchronization.sqlite"
    assert state_path.exists()


def test_archive_sync_pipeline_does_not_touch_destination_when_import_fails(
    tmp_path: Path,
) -> None:
    source = Mock(spec=SourceAdapter)
    source.name = "test-source"
    source.iter_identities.side_effect = RuntimeError("source unavailable")

    destination = _destination()
    paths = ArchivePaths(tmp_path / "archive")

    with pytest.raises(RuntimeError, match="source unavailable"):
        ArchiveSyncPipeline(
            archive_paths=paths,
        ).run(
            source=source,
            destination=destination,
        )

    destination.create_conversation.assert_not_called()
    destination.create_message.assert_not_called()
