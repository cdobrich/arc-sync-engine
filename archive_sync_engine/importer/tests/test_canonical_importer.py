from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from archive_sync_engine.adapters import SourceAdapter
from archive_sync_engine.adapters.source import IdentityDiscoveryBatch, SourceRefreshCursor
from archive_sync_engine.archive import Archive, ArchivePackage
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.asset_store import AssetStore
from archive_sync_engine.importer import ImportState
from archive_sync_engine.importer.discovery_state import DiscoveryPhase, DiscoveryState
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



class DuplicateIdentityBatchSource(FakeSourceAdapter):
    def iter_identity_batches(self, *, resume_cursor=None, batch_size=100):
        del resume_cursor, batch_size
        yield IdentityDiscoveryBatch(
            (
                self._identity,
                self._identity,
                CanonicalIdentity(
                    identity_key=IdentityKey("user-002"),
                    display_name="Second User",
                ),
                self._identity,
            ),
            cursor={"position": 4},
            complete=True,
        )


def test_identity_progress_counts_unique_canonical_identities_not_observations(
    tmp_path: Path,
) -> None:
    """Repeated source observations must not inflate canonical identity progress."""
    source = DuplicateIdentityBatchSource(b"attachment-content")
    statuses = []

    with ArchiveWriter(ArchivePaths(root=tmp_path)) as writer:
        CanonicalImporter().import_source(
            source=source,
            writer=writer,
            asset_store=AssetStore(tmp_path),
            on_status=statuses.append,
        )

    identity_events = [
        event for event in statuses if event.phase == "identities" and event.current
    ]
    assert [(event.current, event.detail) for event in identity_events] == [
        (1, "user-001"),
        (2, "user-002"),
    ]

    with Archive(ArchivePaths(root=tmp_path)) as archive:
        assert tuple(str(identity.identity_key) for identity in archive.iter_identities()) == (
            "user-001",
            "user-002",
        )


def test_resumed_identity_discovery_does_not_recount_persisted_identity(
    tmp_path: Path,
) -> None:
    """A resumed batch containing an already committed identity advances only for new keys."""
    paths = ArchivePaths(root=tmp_path)
    source = DuplicateIdentityBatchSource(b"attachment-content")

    with ArchiveWriter(paths) as writer:
        writer.upsert_identity(source._identity)
        writer.commit()

        statuses = []
        CanonicalImporter().import_source(
            source=source,
            writer=writer,
            asset_store=AssetStore(tmp_path),
            on_status=statuses.append,
            resume_discovery_state=DiscoveryState(
                phase=DiscoveryPhase.IDENTITIES,
                records_committed=1,
                batch_number=1,
                last_record_key="user-001",
                metadata={"adapter": source.name, "cursor": {"position": 1}},
            ),
        )

    identity_events = [
        event for event in statuses if event.phase == "identities" and event.current
    ]
    assert [(event.current, event.detail) for event in identity_events] == [
        (2, "user-002"),
    ]

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
        ("conversations", 0, 1),
        ("conversations", 1, 1),
        ("messages", 0, None),
        ("attachments", 1, 1),
        ("messages", 1, None),
        ("conversations", 1, 1),
        ("refresh", None, None),
    ]
    assert statuses[0].mode == "full"
    assert statuses[-1].traversal == "completed"
    assert statuses[2].detail == "user-001"
    assert statuses[4].detail == "Test Conversation"
    assert statuses[4].completed == 0
    assert statuses[8].completed == 1
    assert statuses[6].detail == "hello.txt"
    assert statuses[7].detail == "message-001"


def test_canonical_importer_reports_resume_conversation_progress_from_checkpoint(
    tmp_path: Path,
) -> None:
    class TwoConversationSource(FakeSourceAdapter):
        def __init__(self) -> None:
            super().__init__(b"attachment-content")
            self._conversation_two = CanonicalConversation(
                id=ConversationId("conversation-002"),
                conversation_type=ConversationType.CHANNEL,
                title="Archive",
            )
            self._message_two = CanonicalMessage(
                id=MessageId("message-002"),
                conversation_id=self._conversation_two.id,
                identity_key=self._identity.identity_key,
                content="Second conversation",
                created_at=datetime(2026, 7, 30, 19, 0, tzinfo=timezone.utc),
            )

        def iter_conversations(self):
            return (self._conversation, self._conversation_two)

        def iter_messages(self, conversation):
            if conversation.id == self._conversation.id:
                return (self._message,)
            return (self._message_two,)

    source = TwoConversationSource()
    statuses = []

    with ArchiveWriter(ArchivePaths(root=tmp_path)) as writer:
        CanonicalImporter().import_source(
            source=source,
            writer=writer,
            asset_store=AssetStore(tmp_path),
            on_status=statuses.append,
            resume_state=ImportState(
                payload={
                    "conversation_id": "conversation-002",
                    "message_id": "message-002",
                }
            ),
        )

    conversation_events = [
        event for event in statuses if event.phase == "conversations"
    ]
    assert [(event.current, event.total, event.completed) for event in conversation_events] == [
        (0, 2, 0),
        (2, 2, 1),
        (2, 2, 2),
    ]
    assert conversation_events[1].detail == "Archive"


def test_full_import_preflights_existing_conversation_before_persistence(
    tmp_path: Path,
) -> None:
    """A full import reports an actionable conflict before writing source data."""
    source = FakeSourceAdapter(b"attachment-content")
    paths = ArchivePaths(root=tmp_path)
    coordinator = CanonicalImportCoordinator(paths)

    coordinator.run(source)

    with pytest.raises(
        ValueError,
        match="Import preflight detected existing Archive conversations.*--resume",
    ):
        coordinator.run(source)

    with Archive(paths) as archive:
        assert tuple(str(identity.identity_key) for identity in archive.iter_identities()) == (
            "user-001",
        )
        assert tuple(str(conversation.id) for conversation in archive.iter_conversations()) == (
            "conversation-001",
        )
        assert tuple(str(message.id) for message in archive.iter_messages()) == (
            "message-001",
        )


def test_full_import_rejects_duplicate_source_conversation_ids_before_writes(
    tmp_path: Path,
) -> None:
    """Duplicate source IDs are diagnosed before any conversation is persisted."""
    source = FakeSourceAdapter(b"attachment-content")
    original_iter_conversations = source.iter_conversations

    def duplicate_conversations():
        conversation = next(iter(original_iter_conversations()))
        yield conversation
        yield conversation

    source.iter_conversations = duplicate_conversations
    paths = ArchivePaths(root=tmp_path)
    ArchivePackage.initialize(paths)

    with pytest.raises(ValueError, match="duplicate canonical conversation IDs"):
        CanonicalImportCoordinator(paths).run(source)

    with Archive(paths) as archive:
        assert tuple(archive.iter_conversations()) == ()
        assert tuple(archive.iter_messages()) == ()


def test_full_import_allows_archive_with_only_unrelated_conversations(
    tmp_path: Path,
) -> None:
    """An unrelated existing conversation does not trigger the duplicate preflight."""
    source = FakeSourceAdapter(b"attachment-content")
    paths = ArchivePaths(root=tmp_path)

    unrelated = CanonicalConversation(
        id=ConversationId("unrelated-conversation"),
        conversation_type=ConversationType.CHANNEL,
        title="Unrelated",
    )
    with ArchiveWriter(paths) as writer:
        writer.add_conversation(unrelated)
        writer.commit()

    CanonicalImportCoordinator(paths).run(source)

    with Archive(paths) as archive:
        assert {
            str(conversation.id) for conversation in archive.iter_conversations()
        } == {
            "conversation-001",
            "unrelated-conversation",
        }


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
    from archive_sync_engine.adapters.source import IdentityDiscoveryBatch, SourceRefreshCursor

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
    from archive_sync_engine.adapters.source import IdentityDiscoveryBatch, SourceRefreshCursor

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



def test_canonical_importer_full_import_reconciles_existing_identity(
    tmp_path: Path,
) -> None:
    """A full import must not fail when its identity already exists."""

    class IdentityOnlySource(FakeSourceAdapter):
        def iter_conversations(self):
            return iter(())

    paths = ArchivePaths(root=tmp_path)
    source = IdentityOnlySource(b"identity retry attachment")
    importer = CanonicalImporter()

    with ArchiveWriter(paths) as writer:
        writer.add_identity(source._identity)

    with ArchiveWriter(paths) as writer:
        asset_store = AssetStore(paths.root)
        importer.import_source(source, writer, asset_store)

    with Archive(paths) as archive:
        assert archive.identity(IdentityKey("user-001")) == source._identity


def test_incremental_import_refreshes_old_message_pin_state_before_cursor_advances(
    tmp_path: Path,
) -> None:
    """Pin changes to old messages must update the canonical Archive.

    Incremental message traversal is intentionally bounded, but pin state is
    channel-scoped and can change independently of message creation time.
    """
    class PinRefreshSource(FakeSourceAdapter):
        def __init__(self) -> None:
            super().__init__(b"attachment")
            self._message = CanonicalMessage(
                id=MessageId("message-001"),
                conversation_id=self._conversation.id,
                identity_key=self._identity.identity_key,
                content="Old message",
                created_at=datetime(
                    2026, 7, 30, 18, 0, tzinfo=timezone.utc
                ),
                pinned=False,
            )
            self._new_message = CanonicalMessage(
                id=MessageId("message-002"),
                conversation_id=self._conversation.id,
                identity_key=self._identity.identity_key,
                content="New message",
                created_at=datetime(
                    2026, 8, 20, 18, 0, tzinfo=timezone.utc
                ),
            )

        def iter_messages_since(self, conversation, cursor):
            assert conversation == self._conversation
            assert cursor.message_id == "message-001"
            yield self._new_message

        def iter_pinned_message_ids(self, conversation):
            assert conversation == self._conversation
            return ()

    source = PinRefreshSource()
    paths = ArchivePaths(root=tmp_path)
    asset_store = AssetStore(paths.root)

    existing = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=source._conversation.id,
        identity_key=source._identity.identity_key,
        content="Old message",
        created_at=datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc),
        pinned=True,
    )

    with ArchiveWriter(paths) as writer:
        writer.upsert_identity(source._identity)
        writer.upsert_conversation(source._conversation)
        writer.upsert_message(existing)

        CanonicalImporter().import_source(
            source=source,
            writer=writer,
            asset_store=asset_store,
            incremental_refresh=True,
            resume_state=ImportState(
                payload={
                    "refresh_cursors": {
                        str(source._conversation.id): SourceRefreshCursor(
                            created_at=datetime(
                                2026, 8, 19, tzinfo=timezone.utc
                            ),
                            message_id="message-001",
                        ).to_json_dict(),
                    },
                },
            ),
            existing_messages_by_conversation={
                str(source._conversation.id): (existing,),
            },
        )

    with Archive(paths) as archive:
        restored = archive.message(MessageId("message-001"))

    assert restored is not None
    assert restored.pinned is False



def test_incremental_pin_refresh_is_authoritative_after_message_upserts(
    tmp_path: Path,
) -> None:
    """Authoritative pin metadata wins over message-window pin flags."""

    class PinRefreshSource(FakeSourceAdapter):
        def __init__(self) -> None:
            super().__init__(b"attachment")
            self._old_pinned = CanonicalMessage(
                id=MessageId("message-old-pinned"),
                conversation_id=self._conversation.id,
                identity_key=self._identity.identity_key,
                content="Old pinned message",
                created_at=datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc),
                pinned=True,
            )
            self._old_unpinned = CanonicalMessage(
                id=MessageId("message-old-unpinned"),
                conversation_id=self._conversation.id,
                identity_key=self._identity.identity_key,
                content="Old unpinned message",
                created_at=datetime(2026, 7, 30, 19, 0, tzinfo=timezone.utc),
                pinned=False,
            )
            self._recent = CanonicalMessage(
                id=MessageId("message-recent"),
                conversation_id=self._conversation.id,
                identity_key=self._identity.identity_key,
                content="Recent message with stale pin flag",
                created_at=datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc),
                pinned=False,
            )

        def iter_messages(self, conversation):
            assert conversation == self._conversation
            yield self._old_pinned
            yield self._old_unpinned
            yield self._recent

        def iter_messages_since(self, conversation, cursor):
            assert conversation == self._conversation
            yield self._recent

        def iter_pinned_message_ids(self, conversation):
            assert conversation == self._conversation
            return (str(self._old_unpinned.id), str(self._recent.id))

    source = PinRefreshSource()
    paths = ArchivePaths(root=tmp_path)
    asset_store = AssetStore(paths.root)

    existing_pinned = source._old_pinned
    existing_unpinned = source._old_unpinned

    with ArchiveWriter(paths) as writer:
        writer.upsert_identity(source._identity)
        writer.upsert_conversation(source._conversation)
        writer.upsert_message(existing_pinned)
        writer.upsert_message(existing_unpinned)

        CanonicalImporter().import_source(
            source=source,
            writer=writer,
            asset_store=asset_store,
            incremental_refresh=True,
            resume_state=ImportState(
                payload={
                    "refresh_cursors": {
                        str(source._conversation.id): SourceRefreshCursor(
                            created_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
                            message_id=str(existing_unpinned.id),
                        ).to_json_dict(),
                    },
                },
            ),
            existing_messages_by_conversation={
                str(source._conversation.id): (
                    existing_pinned,
                    existing_unpinned,
                ),
            },
        )

    with Archive(paths) as archive:
        assert archive.message(existing_pinned.id).pinned is False
        assert archive.message(existing_unpinned.id).pinned is True
        assert archive.message(source._recent.id).pinned is True


def test_incremental_pin_refresh_reconciles_pinned_messages_in_threads(
    tmp_path: Path,
) -> None:
    """Thread messages use the same authoritative pin reconciliation as channels."""

    class ThreadPinRefreshSource(FakeSourceAdapter):
        def __init__(self) -> None:
            super().__init__(b"attachment")
            self._parent = CanonicalConversation(
                id=ConversationId("conversation-parent"),
                conversation_type=ConversationType.CHANNEL,
                title="Parent",
                created_at=datetime(2026, 7, 30, 17, 0, tzinfo=timezone.utc),
            )
            self._thread = CanonicalConversation(
                id=ConversationId("conversation-thread"),
                conversation_type=ConversationType.THREAD,
                title="Thread",
                parent_id=self._parent.id,
                created_at=datetime(2026, 7, 30, 17, 30, tzinfo=timezone.utc),
            )
            self._old_pinned = CanonicalMessage(
                id=MessageId("message-thread-old-pinned"),
                conversation_id=self._thread.id,
                identity_key=self._identity.identity_key,
                content="Thread message now unpinned",
                created_at=datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc),
                pinned=True,
            )
            self._new_pinned = CanonicalMessage(
                id=MessageId("message-thread-new-pinned"),
                conversation_id=self._thread.id,
                identity_key=self._identity.identity_key,
                content="Thread message now pinned",
                created_at=datetime(2026, 7, 30, 18, 1, tzinfo=timezone.utc),
                pinned=False,
            )

        def iter_conversations(self):
            yield self._parent
            yield self._thread

        def iter_messages(self, conversation):
            if conversation == self._thread:
                yield self._old_pinned
                yield self._new_pinned

        def iter_pinned_message_ids(self, conversation):
            if conversation == self._parent:
                return ()
            assert conversation == self._thread
            return (str(self._new_pinned.id),)

    source = ThreadPinRefreshSource()
    paths = ArchivePaths(root=tmp_path)
    asset_store = AssetStore(paths.root)

    with ArchiveWriter(paths) as writer:
        CanonicalImporter().import_source(
            source=source,
            writer=writer,
            asset_store=asset_store,
        )

    with Archive(paths) as archive:
        old_pinned = archive.message(source._old_pinned.id)
        new_pinned = archive.message(source._new_pinned.id)
        thread = archive.conversation(source._thread.id)

    assert old_pinned is not None
    assert new_pinned is not None
    assert thread is not None
    assert old_pinned.conversation_id == source._thread.id
    assert new_pinned.conversation_id == source._thread.id
    assert old_pinned.pinned is False
    assert new_pinned.pinned is True
    assert thread.conversation_type is ConversationType.THREAD
    assert thread.parent_id == source._parent.id


def test_incremental_pin_refresh_reconciles_persisted_messages_without_snapshot(
    tmp_path: Path,
) -> None:
    """Pin refresh must cover archived messages even without a coordinator snapshot."""

    class PinRefreshSource(FakeSourceAdapter):
        def __init__(self) -> None:
            super().__init__(b"attachment")
            self._message_a = CanonicalMessage(
                id=MessageId("message-a"),
                conversation_id=self._conversation.id,
                identity_key=self._identity.identity_key,
                content="Previously pinned; now unpinned",
                created_at=datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc),
                pinned=True,
            )
            self._message_b = CanonicalMessage(
                id=MessageId("message-b"),
                conversation_id=self._conversation.id,
                identity_key=self._identity.identity_key,
                content="Previously unpinned; now pinned",
                created_at=datetime(2026, 7, 30, 19, 0, tzinfo=timezone.utc),
                pinned=False,
            )

        def iter_messages_since(self, conversation, cursor):
            assert conversation == self._conversation
            return ()

        def iter_pinned_message_ids(self, conversation):
            assert conversation == self._conversation
            return (str(self._message_b.id),)

    source = PinRefreshSource()
    paths = ArchivePaths(root=tmp_path)
    asset_store = AssetStore(paths.root)

    with ArchiveWriter(paths) as writer:
        writer.upsert_identity(source._identity)
        writer.upsert_conversation(source._conversation)
        writer.upsert_message(source._message_a)
        writer.upsert_message(source._message_b)

        CanonicalImporter().import_source(
            source=source,
            writer=writer,
            asset_store=asset_store,
            incremental_refresh=True,
            resume_state=ImportState(
                payload={
                    "refresh_cursors": {
                        str(source._conversation.id): SourceRefreshCursor(
                            created_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
                            message_id=str(source._message_b.id),
                        ).to_json_dict(),
                    },
                },
            ),
        )

    with Archive(paths) as archive:
        message_a = archive.message(source._message_a.id)
        message_b = archive.message(source._message_b.id)

    assert message_a is not None
    assert message_b is not None
    assert message_a.pinned is False
    assert message_b.pinned is True


def test_pin_refresh_uses_one_authoritative_snapshot_across_message_traversal(
    tmp_path: Path,
) -> None:
    """Pin reconciliation must not observe a different source state mid-import."""

    class SnapshotSource(FakeSourceAdapter):
        def __init__(self) -> None:
            super().__init__(b"attachment")
            self._message = CanonicalMessage(
                id=MessageId("message-snapshot"),
                conversation_id=self._conversation.id,
                identity_key=self._identity.identity_key,
                content="Snapshot message",
                created_at=datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc),
                pinned=False,
            )
            self.pin_reads = 0

        def iter_messages(self, conversation):
            yield self._message

        def iter_pinned_message_ids(self, conversation):
            self.pin_reads += 1
            if self.pin_reads == 1:
                return (str(self._message.id),)
            return ()

    source = SnapshotSource()
    paths = ArchivePaths(root=tmp_path)
    asset_store = AssetStore(paths.root)

    with ArchiveWriter(paths) as writer:
        CanonicalImporter().import_source(
            source=source,
            writer=writer,
            asset_store=asset_store,
        )

    with Archive(paths) as archive:
        message = archive.message(source._message.id)

    assert message is not None
    assert message.pinned is True
    assert source.pin_reads == 1
