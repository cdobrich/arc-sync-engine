from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from archive_sync_engine.adapters import SourceAdapter
from archive_sync_engine.archive import Archive
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.asset_store import AssetStore
from archive_sync_engine.importer import ImportState
from archive_sync_engine.importer.canonical_coordinator import CanonicalImportCoordinator
from archive_sync_engine.importer.canonical_importer import (
    CanonicalImporter,
)
from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
)
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.ids import (
    AttachmentId,
    ConversationId,
    IdentityKey,
    MessageId,
)


class FakeSourceAdapter(SourceAdapter):
    """
    Deterministic source adapter used by the canonical importer tests.
    """

    def __init__(
        self,
        attachment_content: bytes,
    ) -> None:

        import hashlib

        attachment_sha256 = hashlib.sha256(
            attachment_content,
        ).hexdigest()

        self._identity = CanonicalIdentity(
            identity_key=IdentityKey("user-001"),
            display_name="Test User",
        )

        self._conversation = CanonicalConversation(
            id=ConversationId("conversation-001"),
            conversation_type=ConversationType.CHANNEL,
            title="Test Conversation",
            created_at=datetime(
                2026,
                7,
                30,
                17,
                0,
                tzinfo=timezone.utc,
            ),
        )

        self._attachment = CanonicalAttachment(
            id=AttachmentId("attachment-001"),
            filename="hello.txt",
            content_type="text/plain",
            size=len(attachment_content),
            sha256=attachment_sha256,
        )

        self._message = CanonicalMessage(
            id=MessageId("message-001"),
            conversation_id=self._conversation.id,
            identity_key=self._identity.identity_key,
            content="Hello from the source.",
            created_at=datetime(
                2026,
                7,
                30,
                18,
                0,
                tzinfo=timezone.utc,
            ),
            attachments=(
                self._attachment,
            ),
        )

        self._attachment_content = attachment_content

    @property
    def name(self) -> str:
        return "Fake Source"

    def iter_conversations(
        self,
    ):
        yield self._conversation

    def iter_identities(
        self,
    ):
        yield self._identity

    def iter_messages(
        self,
        conversation: CanonicalConversation,
    ):
        assert conversation == self._conversation
        yield self._message

    def attachment_bytes(
        self,
        attachment: CanonicalAttachment,
    ) -> bytes:

        assert attachment == self._attachment

        return self._attachment_content


def test_canonical_importer_imports_source_into_archive(
    tmp_path: Path,
) -> None:
    """
    CanonicalImporter imports canonical identities, conversations,
    messages, and attachment bytes into an Archive Package.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    attachment_content = b"hello attachment"

    source = FakeSourceAdapter(
        attachment_content,
    )

    importer = CanonicalImporter()

    with ArchiveWriter(
        paths,
    ) as writer:

        asset_store = AssetStore(
            paths.root,
        )

        importer.import_source(
            source,
            writer,
            asset_store,
        )

    #
    # Archive is the read-only verification boundary.
    #

    with Archive(
        paths,
    ) as archive:

        identity = archive.identity(
            IdentityKey("user-001"),
        )

        assert identity == source._identity

        conversation = archive.conversation(
            ConversationId("conversation-001"),
        )

        assert conversation == source._conversation

        message = archive.message(
            MessageId("message-001"),
        )

        assert message == source._message

        attachment = archive.attachment(
            AttachmentId("attachment-001"),
        )

        assert attachment == source._attachment

        assert asset_store.get(
            source._attachment.sha256,
        ) == attachment_content

def test_canonical_import_coordinator_persists_import_state(
    tmp_path: Path,
) -> None:
    """
    CanonicalImportCoordinator can persist and recover opaque
    importer-owned state.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    coordinator = CanonicalImportCoordinator(
        paths,
    )

    state = ImportState(
        payload={
            "source_cursor": "cursor-001",
            "conversation_id": "conversation-001",
            "message_id": "message-001",
        },
    )

    coordinator.save_import_state(
        state,
    )

    restored = coordinator.load_import_state()

    assert restored == state

def test_canonical_importer_reports_progress(
    tmp_path: Path,
) -> None:
    """
    CanonicalImporter reports opaque progress after successfully
    importing each message.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    attachment_content = b"attachment-content"

    source = FakeSourceAdapter(
        attachment_content=attachment_content,
    )

    with ArchiveWriter(
        paths,
    ) as writer:

        reported: list[ImportState] = []

        importer = CanonicalImporter()

        importer.import_source(
            source=source,
            writer=writer,
            asset_store=AssetStore(
                paths.root,
            ),
            on_progress=reported.append,
        )

    assert reported == [
        ImportState(
            payload={
                "conversation_id": "conversation-001",
                "message_id": "message-001",
            },
        ),
    ]

def test_canonical_import_coordinator_persists_import_progress(
    tmp_path: Path,
) -> None:
    """
    CanonicalImportCoordinator persists the latest progress reported
    by CanonicalImporter.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    attachment_content = b"attachment-content"

    source = FakeSourceAdapter(
        attachment_content=attachment_content,
    )

    coordinator = CanonicalImportCoordinator(
        paths,
    )

    coordinator.run(
        source,
    )

    state = coordinator.load_import_state()

    assert state.payload == {
        "conversation_id": "conversation-001",
        "message_id": "message-001",
    }

def test_canonical_importer_reports_user_facing_status_without_source_specific_fields(
    tmp_path: Path,
) -> None:
    paths = ArchivePaths(root=tmp_path)
    source = FakeSourceAdapter(b"attachment-content")
    statuses = []

    with ArchiveWriter(paths) as writer:
        CanonicalImporter().import_source(
            source=source,
            writer=writer,
            asset_store=AssetStore(paths.root),
            on_status=statuses.append,
        )

    assert [(item.phase, item.current, item.total) for item in statuses] == [
        ("refresh", None, None),
        ("identities", 0, None),
        ("identities", 1, None),
        ("conversations", 0, None),
        ("conversations", 1, None),
        ("messages", 0, None),
        ("attachments", 1, 1),
        ("messages", 1, None),
        ("refresh", None, None),
    ]
    assert statuses[0].mode == "full"
    assert statuses[-1].traversal == "completed"
    assert statuses[2].detail == "user-001"
    assert statuses[4].detail == "Test Conversation"
    assert statuses[6].detail == "hello.txt"
    assert statuses[7].detail == "message-001"


def test_incremental_refresh_reuses_content_addressed_attachment_without_download(
    tmp_path: Path,
) -> None:
    """A refresh never downloads an attachment whose SHA-256 is already stored."""
    source = FakeSourceAdapter(b"attachment-content")
    download_count = 0

    original = source.attachment_bytes

    def counted_download(attachment):
        nonlocal download_count
        download_count += 1
        return original(attachment)

    source.attachment_bytes = counted_download

    paths = ArchivePaths(root=tmp_path)
    coordinator = CanonicalImportCoordinator(paths)
    coordinator.run(source)
    assert download_count == 1

    coordinator.run(source, resume=True)

    assert download_count == 1


def test_incremental_refresh_uses_adapter_incremental_message_traversal(
    tmp_path: Path,
) -> None:
    """A completed refresh uses the adapter's source-aware cursor API."""
    from archive_sync_engine.adapters.source import SourceRefreshCursor

    class IncrementalSource(FakeSourceAdapter):
        def __init__(self) -> None:
            super().__init__(b"attachment-content")
            self.incremental_cursors = []
            self._refresh = False

        def iter_messages_since(self, conversation, cursor):
            self.incremental_cursors.append(cursor)
            if self._refresh:
                yield CanonicalMessage(
                    id=MessageId("message-002"),
                    conversation_id=conversation.id,
                    identity_key=self._identity.identity_key,
                    content="new",
                    created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                )

    paths = ArchivePaths(root=tmp_path)
    source = IncrementalSource()
    coordinator = CanonicalImportCoordinator(paths)

    coordinator.run(source)
    source._refresh = True
    coordinator.run(source, resume=True)

    assert source.incremental_cursors == [
        SourceRefreshCursor(
            created_at=datetime(2026, 7, 30, 18, tzinfo=timezone.utc),
            message_id="message-001",
        )
    ]

    with Archive(paths) as archive:
        assert tuple(str(message.id) for message in archive.iter_messages()) == (
            "message-001",
            "message-002",
        )


def test_import_rate_limiter_applies_message_and_channel_delays(tmp_path: Path) -> None:
    """Import pacing occurs between messages and conversations."""
    source = FakeSourceAdapter(b"attachment-content")
    conversation_two = CanonicalConversation(
        id=ConversationId("conversation-002"),
        conversation_type=ConversationType.CHANNEL,
        title="Second Conversation",
        created_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )
    original_iter_conversations = source.iter_conversations
    source.iter_conversations = lambda: iter(
        (*tuple(original_iter_conversations()), conversation_two)
    )

    original_iter_messages = source.iter_messages
    source.iter_messages = lambda conversation: (
        original_iter_messages(conversation)
        if conversation.id == source._conversation.id
        else iter(())
    )

    sleeps: list[float] = []
    from archive_sync_engine.rate_limit import OperationRateLimiter

    limiter = OperationRateLimiter(
        between_messages_seconds=0.5,
        between_channels_seconds=2.0,
        sleep=sleeps.append,
        monotonic=lambda: 100.0,
    )

    paths = ArchivePaths(root=tmp_path)
    with ArchiveWriter(paths) as writer:
        CanonicalImporter().import_source(
            source=source,
            writer=writer,
            asset_store=AssetStore(paths.root),
            rate_limiter=limiter,
        )

    # The source has one message in each conversation. Only the channel
    # transition requires pacing; the first message in each channel does not
    # incur a message delay.
    assert sleeps == [2.0]


def test_incremental_refresh_reports_source_cursor_diagnostics(tmp_path: Path) -> None:
    from archive_sync_engine.adapters.source import SourceRefreshCursor

    class IncrementalSource(FakeSourceAdapter):
        @property
        def incremental_refresh_lookback(self):
            from datetime import timedelta
            return timedelta(days=7)

        def iter_messages_since(self, conversation, cursor):
            self.cursor = cursor
            return iter(())

    source = IncrementalSource(b"attachment-content")
    statuses = []
    paths = ArchivePaths(root=tmp_path)

    with ArchiveWriter(paths) as writer:
        CanonicalImporter().import_source(
            source=source,
            writer=writer,
            asset_store=AssetStore(paths.root),
            on_status=statuses.append,
            resume_state=ImportState(
                payload={
                    "refresh_cursors": {
                        "conversation-001": SourceRefreshCursor(
                            created_at=datetime(2026, 7, 30, 18, tzinfo=timezone.utc),
                            message_id="message-001",
                        ).to_json_dict(),
                    },
                },
            ),
            incremental_refresh=True,
        )

    refresh_events = [event for event in statuses if event.phase == "refresh"]
    assert refresh_events[0].mode == "incremental"
    assert refresh_events[0].traversal == "adapter_incremental"
    assert refresh_events[1].cursor == "message-001"
    assert refresh_events[1].lookback_seconds == 7 * 24 * 60 * 60
    assert refresh_events[-1].traversal == "completed"
    assert refresh_events[-1].examined == 0


def test_canonical_importer_ignores_absent_optional_custom_emoji_hook(tmp_path) -> None:
    """Older/duck-typed source test doubles may omit optional emoji hooks."""
    from types import SimpleNamespace

    source = SimpleNamespace(
        name="minimal source",
        iter_identities=lambda: (),
        iter_conversations=lambda: (),
        iter_custom_emojis=None,
    )
    paths = ArchivePaths(tmp_path / "archive")
    with ArchiveWriter(paths) as writer:
        CanonicalImporter().import_source(
            source,
            writer,
            AssetStore(paths.root),
        )
        writer.commit()
