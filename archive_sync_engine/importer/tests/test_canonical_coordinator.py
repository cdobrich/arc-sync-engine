from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from archive_sync_engine.adapters import SourceAdapter
from archive_sync_engine.archive import Archive
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.importer.canonical_coordinator import (
    CanonicalImportCoordinator,
)
from archive_sync_engine.models import (
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
)
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.ids import (
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

    coordinator.run(
        source,
    )

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
