from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from archive_sync_engine.adapters import SourceAdapter
from archive_sync_engine.archive import Archive
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.importer.canonical_coordinator import (
    CanonicalImportCoordinator,
    ImportReport,
)
from archive_sync_engine.models import (
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
    CanonicalAttachment,
    CanonicalReaction,
)
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.ids import (
    AttachmentId,
    ConversationId,
    IdentityKey,
    MessageId,
)


class FakeSourceAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "Fake"

    def iter_conversations(
        self,
    ):
        return (
            CanonicalConversation(
                id=ConversationId(
                    "conversation-001",
                ),
                conversation_type=ConversationType.CHANNEL,
                title="General",
            ),
        )

    def iter_identities(
        self,
    ):
        return (
            CanonicalIdentity(
                identity_key=IdentityKey(
                    "identity-001",
                ),
                display_name="Alice",
            ),
        )

    def iter_messages(
        self,
        conversation: CanonicalConversation,
    ):
        return (
            CanonicalMessage(
                id=MessageId(
                    "message-001",
                ),
                conversation_id=conversation.id,
                identity_key=IdentityKey(
                    "identity-001",
                ),
                content="Hello from the source.",
                created_at=datetime(
                    2026,
                    7,
                    31,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
        )

    def attachment_bytes(
        self,
        attachment,
    ) -> bytes:
        raise AssertionError(
            "The test source contains no attachments."
        )


def test_canonical_import_coordinator_imports_source(
    tmp_path: Path,
) -> None:
    """
    CanonicalImportCoordinator executes a complete canonical import
    and produces an Archive that can subsequently be opened.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    source = FakeSourceAdapter()

    coordinator = CanonicalImportCoordinator(
        paths,
    )

    report = coordinator.run(
        source,
    )

    assert isinstance(report, ImportReport)
    assert report.identities == 1
    assert report.conversations == 1
    assert report.messages == 1
    assert report.attachments == 0

    with Archive(
        paths,
    ) as archive:

        conversations = tuple(
            archive.iter_conversations(),
        )

        identities = tuple(
            archive.iter_identities(),
        )

        messages = tuple(
            archive.iter_messages(),
        )

        assert identities == (
            CanonicalIdentity(
                identity_key=IdentityKey(
                    "identity-001",
                ),
                display_name="Alice",
            ),
        )

        assert conversations == (
            CanonicalConversation(
                id=ConversationId(
                    "conversation-001",
                ),
                conversation_type=ConversationType.CHANNEL,
                title="General",
            ),
        )

        assert messages == (
            CanonicalMessage(
                id=MessageId(
                    "message-001",
                ),
                conversation_id=ConversationId(
                    "conversation-001",
                ),
                identity_key=IdentityKey(
                    "identity-001",
                ),
                content="Hello from the source.",
                created_at=datetime(
                    2026,
                    7,
                    31,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
            ),
        )

from datetime import datetime, timezone
from pathlib import Path

from archive_sync_engine.archive.package import ArchivePackage
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.importer.canonical_coordinator import (
    CanonicalImportCoordinator,
    ImportReport,
)
from archive_sync_engine.sync.session import SyncSession, SyncDirection


def test_canonical_import_coordinator_persists_completed_session(
    tmp_path: Path,
) -> None:
    """
    A completed canonical import persists its synchronization session
    in the Archive Package.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    source = FakeSourceAdapter()

    coordinator = CanonicalImportCoordinator(
        paths,
    )

    coordinator.run(
        source,
    )

    package = ArchivePackage(
        paths,
    )

    session = package.load_session()

    assert isinstance(
        session,
        SyncSession,
    )

    assert session.completed is True
    assert session.paused is False
    assert session.cancelled is False
    assert session.error is None

    assert session.started_at.tzinfo is not None
    assert session.updated_at.tzinfo is not None

    assert session.updated_at >= session.started_at

class FailingSourceAdapter(
    SourceAdapter,
):
    @property
    def name(self) -> str:
        return "Failing"

    def iter_identities(self):
        raise RuntimeError(
            "source import failed"
        )

    def iter_conversations(self):
        raise AssertionError(
            "iter_conversations() should not be reached."
        )

    def iter_messages(
        self,
        conversation,
    ):
        raise AssertionError(
            "iter_messages() should not be reached."
        )

    def attachment_bytes(
        self,
        attachment,
    ) -> bytes:
        raise AssertionError(
            "attachment_bytes() should not be reached."
        )

def test_canonical_import_coordinator_persists_failed_session(
    tmp_path: Path,
) -> None:
    """
    A failed canonical import persists the failure in its session
    before re-raising the original exception.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    source = FailingSourceAdapter()

    coordinator = CanonicalImportCoordinator(
        paths,
    )

    try:
        coordinator.run(
            source,
        )
    except RuntimeError as exc:
        assert str(exc) == "source import failed"
    else:
        raise AssertionError(
            "CanonicalImportCoordinator.run() "
            "should have raised RuntimeError."
        )

    package = ArchivePackage(
        paths,
    )

    session = package.load_session()

    assert session.completed is False
    assert session.paused is False
    assert session.cancelled is False
    assert session.error == "source import failed"
    assert session.updated_at >= session.started_at

def test_canonical_import_coordinator_loads_persisted_session(
    tmp_path: Path,
) -> None:
    """
    CanonicalImportCoordinator can recover the persisted session
    created by a previous import.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    source = FakeSourceAdapter()

    coordinator = CanonicalImportCoordinator(
        paths,
    )

    coordinator.run(
        source,
    )

    restored = coordinator.load_session()

    assert restored.direction is SyncDirection.IMPORT
    assert restored.completed is True
    assert restored.paused is False
    assert restored.cancelled is False
    assert restored.error is None
    assert restored.started_at.tzinfo is not None
    assert restored.updated_at.tzinfo is not None
    assert restored.updated_at >= restored.started_at

def test_canonical_import_coordinator_has_no_session_before_run(
    tmp_path: Path,
) -> None:
    """
    A newly created import coordinator has no persisted session until
    an import is started.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    coordinator = CanonicalImportCoordinator(
        paths,
    )

    with pytest.raises(
        FileNotFoundError,
    ):
        coordinator.load_session()
class ResumableSourceAdapter(SourceAdapter):
    def __init__(self) -> None:
        self.fail_second_message = True
        self.message_visits: list[str] = []
        self._identity = CanonicalIdentity(
            identity_key=IdentityKey("identity-001"),
            display_name="Alice",
        )
        self._conversation = CanonicalConversation(
            id=ConversationId("conversation-001"),
            conversation_type=ConversationType.CHANNEL,
            title="General",
        )
        self._messages = (
            CanonicalMessage(
                id=MessageId("message-001"),
                conversation_id=self._conversation.id,
                identity_key=self._identity.identity_key,
                content="first",
                created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            ),
            CanonicalMessage(
                id=MessageId("message-002"),
                conversation_id=self._conversation.id,
                identity_key=self._identity.identity_key,
                content="second",
                created_at=datetime(2026, 8, 1, 0, 1, tzinfo=timezone.utc),
            ),
        )

    @property
    def name(self) -> str:
        return "Resumable"

    def iter_identities(self):
        yield self._identity

    def iter_conversations(self):
        yield self._conversation

    def iter_messages(self, conversation):
        for message in self._messages:
            self.message_visits.append(str(message.id))
            if message.id == MessageId("message-002") and self.fail_second_message:
                raise RuntimeError("second message failed")
            yield message

    def attachment_bytes(self, attachment):
        raise AssertionError("No attachments are used in this test.")


def test_canonical_import_coordinator_commits_completed_messages_before_failure(
    tmp_path: Path,
) -> None:
    paths = ArchivePaths(root=tmp_path)
    source = ResumableSourceAdapter()
    coordinator = CanonicalImportCoordinator(paths)

    with pytest.raises(RuntimeError, match="second message failed"):
        coordinator.run(source)

    with Archive(paths) as archive:
        assert tuple(message.id for message in archive.iter_messages()) == (
            MessageId("message-001"),
        )

    state = coordinator.load_import_state()
    assert state.payload == {
        "conversation_id": "conversation-001",
        "message_id": "message-001",
    }


def test_canonical_import_coordinator_resumes_from_last_committed_message(
    tmp_path: Path,
) -> None:
    paths = ArchivePaths(root=tmp_path)
    source = ResumableSourceAdapter()
    coordinator = CanonicalImportCoordinator(paths)

    with pytest.raises(RuntimeError, match="second message failed"):
        coordinator.run(source)

    source.fail_second_message = False
    source.message_visits.clear()

    coordinator.run(source, resume=True)

    assert source.message_visits == [
        "message-001",
        "message-002",
    ]

    with Archive(paths) as archive:
        assert tuple(message.id for message in archive.iter_messages()) == (
            MessageId("message-001"),
            MessageId("message-002"),
        )

    state = coordinator.load_import_state()
    assert state.payload == {
        "conversation_id": "conversation-001",
        "message_id": "message-002",
    }

    session = coordinator.load_session()
    assert session.completed is True
    assert session.error is None


def test_completed_import_resume_refreshes_new_messages_attachments_and_reactions(
    tmp_path: Path,
) -> None:
    """Resuming a completed import reconciles the current source state."""
    import hashlib

    class MutableSource(SourceAdapter):
        def __init__(self) -> None:
            self.refresh = False
            self.content = "initial"
            self.reaction = False
            self._attachment_content = b"new attachment"

        @property
        def name(self) -> str:
            return "Mutable"

        def iter_identities(self):
            identities = [
                CanonicalIdentity(
                    identity_key=IdentityKey("identity-001"),
                    display_name="Alice",
                )
            ]
            if self.reaction:
                identities.append(
                    CanonicalIdentity(
                        identity_key=IdentityKey("identity-002"),
                        display_name="Bob",
                    )
                )
            return tuple(identities)

        def iter_conversations(self):
            return (
                CanonicalConversation(
                    id=ConversationId("conversation-001"),
                    conversation_type=ConversationType.CHANNEL,
                    title="General",
                ),
            )

        def iter_messages(self, conversation):
            messages = [
                CanonicalMessage(
                    id=MessageId("message-001"),
                    conversation_id=conversation.id,
                    identity_key=IdentityKey("identity-001"),
                    content=self.content,
                    created_at=datetime(2026, 7, 31, 12, tzinfo=timezone.utc),
                    reactions=(
                        CanonicalReaction(
                            identity_key=IdentityKey("identity-002"),
                            emoji="👍",
                        ),
                    )
                    if self.reaction
                    else (),
                ),
            ]
            if self.refresh:
                content = self._attachment_content
                attachment = CanonicalAttachment(
                    id=AttachmentId("attachment-001"),
                    filename="new.txt",
                    content_type="text/plain",
                    size=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                )
                messages.append(
                    CanonicalMessage(
                        id=MessageId("message-002"),
                        conversation_id=conversation.id,
                        identity_key=IdentityKey("identity-001"),
                        content="",
                        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                        attachments=(attachment,),
                    )
                )
            return tuple(messages)

        def attachment_bytes(self, attachment):
            return self._attachment_content

    paths = ArchivePaths(root=tmp_path)
    source = MutableSource()
    coordinator = CanonicalImportCoordinator(paths)

    first = coordinator.run(source)
    assert (first.messages, first.attachments) == (1, 0)

    source.refresh = True
    source.reaction = True
    source.content = "updated"

    refreshed = coordinator.run(source, resume=True)
    assert (refreshed.messages, refreshed.attachments) == (2, 1)

    with Archive(paths) as archive:
        messages = tuple(archive.iter_messages())
        assert len(messages) == 2
        assert messages[0].content == "updated"
        assert messages[0].reactions == (
            CanonicalReaction(
                identity_key=IdentityKey("identity-002"),
                emoji="👍",
            ),
        )
        assert messages[1].attachments[0].id == AttachmentId("attachment-001")


def test_incremental_refresh_reconciles_mutable_message_state_from_source_window(
    tmp_path: Path,
) -> None:
    """Incremental refresh can update an old message without a full scan."""
    from archive_sync_engine.adapters.source import SourceRefreshCursor

    class MutableIncrementalSource(SourceAdapter):
        def __init__(self) -> None:
            self.refresh = False
            self.since_cursors = []
            self._identity = CanonicalIdentity(
                identity_key=IdentityKey("identity-001"),
                display_name="Alice",
            )
            self._reaction_identity = CanonicalIdentity(
                identity_key=IdentityKey("identity-002"),
                display_name="Bob",
            )
            self._conversation = CanonicalConversation(
                id=ConversationId("conversation-001"),
                conversation_type=ConversationType.CHANNEL,
                title="General",
            )

        @property
        def name(self) -> str:
            return "Mutable incremental"

        def iter_identities(self):
            yield self._identity

        def iter_identities_since(self, cursors):
            if self.refresh:
                yield self._identity
                yield self._reaction_identity

        def iter_conversations(self):
            yield self._conversation

        def iter_messages(self, conversation):
            yield CanonicalMessage(
                id=MessageId("message-001"),
                conversation_id=conversation.id,
                identity_key=self._identity.identity_key,
                content="original",
                created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )

        def iter_messages_since(self, conversation, cursor):
            self.since_cursors.append(cursor)
            yield CanonicalMessage(
                id=MessageId("message-001"),
                conversation_id=conversation.id,
                identity_key=self._identity.identity_key,
                content="edited",
                created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                reactions=(
                    CanonicalReaction(
                        identity_key=self._reaction_identity.identity_key,
                        emoji="👍",
                    ),
                ),
            )

        def attachment_bytes(self, attachment):
            raise AssertionError("No attachments are used in this test.")

    paths = ArchivePaths(root=tmp_path)
    source = MutableIncrementalSource()
    coordinator = CanonicalImportCoordinator(paths)

    coordinator.run(source)
    source.refresh = True
    coordinator.run(source, resume=True)

    assert source.since_cursors == [
        SourceRefreshCursor(
            created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            message_id="message-001",
        )
    ]

    with Archive(paths) as archive:
        message = archive.message(MessageId("message-001"))
        assert message.content == "edited"
        assert message.reactions == (
            CanonicalReaction(
                identity_key=IdentityKey("identity-002"),
                emoji="👍",
            ),
        )


def test_interrupted_import_resume_uses_last_committed_source_cursor(
    tmp_path: Path,
) -> None:
    """An interrupted import can continue from its durable source cursor."""
    from archive_sync_engine.adapters.source import SourceRefreshCursor

    class InterruptibleSource(ResumableSourceAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.incremental_visits: list[str] = []
            self.use_incremental = False

        def iter_messages_since(self, conversation, cursor):
            self.incremental_visits.append(str(cursor.message_id))
            for message in self._messages:
                if message.created_at > cursor.created_at:
                    yield message

    paths = ArchivePaths(root=tmp_path)
    source = InterruptibleSource()
    coordinator = CanonicalImportCoordinator(paths)

    with pytest.raises(RuntimeError, match="second message failed"):
        coordinator.run(source)

    assert coordinator.load_import_cursors() == {
        "conversation-001": SourceRefreshCursor(
            created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            message_id="message-001",
        )
    }

    source.fail_second_message = False
    source.message_visits.clear()
    coordinator.run(source, resume=True)

    assert source.incremental_visits == ["message-001"]
    with Archive(paths) as archive:
        assert tuple(str(message.id) for message in archive.iter_messages()) == (
            "message-001",
            "message-002",
        )
