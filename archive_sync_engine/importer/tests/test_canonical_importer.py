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