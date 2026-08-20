"""Tests for the canonical export facade."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from archive_sync_engine.adapters import (
    DestinationCapabilities,
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)
from archive_sync_engine.archive import Archive, ArchivePaths, ArchiveWriter
from archive_sync_engine.asset_store import AssetStore
from archive_sync_engine.exporter import CanonicalExporter
from archive_sync_engine.repository import SQLiteStateRepository
from archive_sync_engine.models import (
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
)
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.ids import ConversationId, IdentityKey, MessageId


class RecordingDestination:
    """Minimal destination used to prove exporter uses current operation APIs."""

    name = "recording"

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    @property
    def capabilities(self) -> DestinationCapabilities:
        return DestinationCapabilities()

    def create_conversation(self, conversation):
        self.calls.append(("create_conversation", conversation))
        return DestinationConversationRef(f"dest-{conversation.id}")

    def update_conversation(self, conversation, destination):
        raise AssertionError("unexpected conversation update")

    def delete_conversation(self, destination):
        raise AssertionError("unexpected conversation delete")

    def create_identity(self, identity):
        self.calls.append(("create_identity", identity))
        return DestinationIdentityRef(f"dest-{identity.identity_key}")

    def update_identity(self, identity, destination):
        raise AssertionError("unexpected identity update")

    def delete_identity(self, destination):
        raise AssertionError("unexpected identity delete")

    def upload_attachment(self, attachment, data):
        self.calls.append(("upload_attachment", (attachment, data)))
        return type("AttachmentRef", (), {"id": str(attachment.id)})()

    def add_attachment(self, message, attachment, data):
        raise AssertionError("unexpected incremental attachment")

    def remove_attachment(self, message, attachment):
        raise AssertionError("unexpected attachment removal")

    def reorder_attachments(self, message, attachments):
        raise AssertionError("unexpected attachment reorder")

    def create_message(
        self,
        message,
        destination,
        attachments=(),
        reply_to=None,
    ):
        self.calls.append(
            (
                "create_message",
                (message, destination, attachments, reply_to),
            )
        )
        return DestinationMessageRef(
            f"dest-{message.id}",
            conversation_id=destination.id,
        )

    def edit_message(self, message, destination):
        raise AssertionError("unexpected message edit")

    def delete_message(self, destination):
        raise AssertionError("unexpected message delete")

    def set_message_reply(self, message, reply_to):
        raise AssertionError("unexpected reply operation")

    def pin_message(self, message):
        self.calls.append(("pin_message", message))

    def unpin_message(self, message):
        raise AssertionError("unexpected unpin")

    def add_reaction(self, message, reaction):
        self.calls.append(("add_reaction", (message, reaction)))

    def remove_reaction(self, message, reaction):
        raise AssertionError("unexpected reaction removal")


def _write_archive(paths: ArchivePaths) -> tuple[Archive, AssetStore]:
    identity = CanonicalIdentity(
        identity_key=IdentityKey("identity-1"),
        display_name="Identity One",
    )
    conversation = CanonicalConversation(
        id=ConversationId("conversation-1"),
        conversation_type=ConversationType.CHANNEL,
        title="general",
    )
    message = CanonicalMessage(
        id=MessageId("message-1"),
        conversation_id=conversation.id,
        identity_key=identity.identity_key,
        content="hello",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    with ArchiveWriter(paths) as writer:
        writer.add_identity(identity)
        writer.add_conversation(conversation)
        writer.add_message(message)

    return Archive(paths), AssetStore(paths.root)


def test_canonical_exporter_uses_current_operation_pipeline(
    tmp_path: Path,
) -> None:
    paths = ArchivePaths(root=tmp_path / "archive")
    archive, asset_store = _write_archive(paths)
    destination = RecordingDestination()

    report = CanonicalExporter().export(
        archive,
        destination,
        asset_store,
    )

    assert report.executed_operations == 3
    assert [name for name, _ in destination.calls] == [
        "create_conversation",
        "create_identity",
        "create_message",
    ]



def test_canonical_exporter_reuses_durable_synchronization_state(
    tmp_path: Path,
) -> None:
    paths = ArchivePaths(root=tmp_path / "archive")
    archive, asset_store = _write_archive(paths)
    destination = RecordingDestination()
    state_path = paths.root / "synchronization.sqlite"

    with SQLiteStateRepository(state_path) as repository:
        first = CanonicalExporter().export(
            archive,
            destination,
            asset_store,
            state_repository=repository,
        )
        first_call_count = len(destination.calls)

        second = CanonicalExporter().export(
            archive,
            destination,
            asset_store,
            state_repository=repository,
        )

    assert first.executed_operations == 3
    assert second.executed_operations == 0
    assert len(destination.calls) == first_call_count


def test_canonical_exporter_forwards_progress_callback(
    tmp_path: Path,
) -> None:
    paths = ArchivePaths(root=tmp_path / "archive")
    archive, asset_store = _write_archive(paths)
    destination = RecordingDestination()
    reported = []

    CanonicalExporter().export(
        archive,
        destination,
        asset_store,
        on_status=reported.append,
    )

    assert [(event.phase, event.current, event.detail) for event in reported] == [
        ("conversations", 1, "conversation-1"),
        ("identities", 1, "identity-1"),
        ("messages", 1, "message-1"),
    ]


def test_canonical_exporter_preserves_destination_message_reference_contract(
    tmp_path: Path,
) -> None:
    paths = ArchivePaths(root=tmp_path / "archive")
    archive, asset_store = _write_archive(paths)
    destination = RecordingDestination()

    CanonicalExporter().export(
        archive,
        destination,
        asset_store,
    )

    _, payload = destination.calls[-1]
    _, conversation_ref, attachments, reply_to = payload

    assert conversation_ref == DestinationConversationRef(
        "dest-conversation-1",
    )
    assert attachments == ()
    assert reply_to is None
