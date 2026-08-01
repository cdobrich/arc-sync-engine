"""
Tests for the initial destination execution vertical slice.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pathlib import Path

from archive_sync_engine.adapters.capabilities import (
    DestinationCapabilities,
)
from archive_sync_engine.adapters.destination import (
    DestinationAdapter,
)
from archive_sync_engine.adapters.references import (
    DestinationAttachmentRef,
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)
from archive_sync_engine.archive.archive import Archive
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.executor.executor import OperationExecutor
from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
    CanonicalReaction,
)
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.ids import (
    ConversationId,
    IdentityKey,
    MessageId,
)


EXPECTED_IDENTITY = CanonicalIdentity(
    identity_key=IdentityKey(
        "user-001",
    ),
    display_name="Test User",
)


EXPECTED_CONVERSATION = CanonicalConversation(
    id=ConversationId(
        "conversation-001",
    ),
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


EXPECTED_MESSAGE = CanonicalMessage(
    id=MessageId(
        "message-001",
    ),
    conversation_id=EXPECTED_CONVERSATION.id,
    identity_key=EXPECTED_IDENTITY.identity_key,
    content="Hello from the archive.",
    created_at=datetime(
        2026,
        7,
        30,
        18,
        0,
        tzinfo=timezone.utc,
    ),
)


class FakeDestinationAdapter(
    DestinationAdapter,
):
    """
    Deterministic destination used by Executor tests.
    """

    def __init__(
        self,
    ) -> None:
        self.created_conversations = []
        self.created_messages = []

    @property
    def name(
        self,
    ) -> str:
        return "Fake Destination"

    @property
    def capabilities(
        self,
    ) -> DestinationCapabilities:
        return DestinationCapabilities()

    def create_conversation(
        self,
        conversation: CanonicalConversation,
    ) -> DestinationConversationRef:

        self.created_conversations.append(
            conversation,
        )

        return DestinationConversationRef(
            id=f"destination-{conversation.id}",
        )

    def update_conversation(
        self,
        conversation: CanonicalConversation,
    ) -> None:
        raise NotImplementedError

    def delete_conversation(
        self,
        conversation_id: ConversationId,
    ) -> None:
        raise NotImplementedError

    def create_identity(
        self,
        identity: CanonicalIdentity,
    ) -> DestinationIdentityRef:
        raise NotImplementedError

    def update_identity(
        self,
        identity: CanonicalIdentity,
    ) -> None:
        raise NotImplementedError

    def upload_attachment(
        self,
        attachment: CanonicalAttachment,
        data: bytes,
    ) -> DestinationAttachmentRef:
        raise NotImplementedError

    def create_message(
        self,
        message: CanonicalMessage,
    ) -> DestinationMessageRef:

        self.created_messages.append(
            message,
        )

        return DestinationMessageRef(
            id=f"destination-{message.id}",
        )

    def edit_message(
        self,
        message: CanonicalMessage,
    ) -> None:
        raise NotImplementedError

    def delete_message(
        self,
        message_id: MessageId,
    ) -> None:
        raise NotImplementedError

    def pin_message(
        self,
        message_id: MessageId,
    ) -> None:
        raise NotImplementedError

    def unpin_message(
        self,
        message_id: MessageId,
    ) -> None:
        raise NotImplementedError

    def add_reaction(
        self,
        message_id: MessageId,
        reaction: CanonicalReaction,
    ) -> None:
        raise NotImplementedError

    def remove_reaction(
        self,
        message_id: MessageId,
        reaction: CanonicalReaction,
    ) -> None:
        raise NotImplementedError


def _create_archive(
    paths: ArchivePaths,
) -> None:
    """
    Create a deterministic archive containing the expected test data.
    """

    with ArchiveWriter(
        paths,
    ) as writer:

        writer.add_identity(
            EXPECTED_IDENTITY,
        )

        writer.add_conversation(
            EXPECTED_CONVERSATION,
        )

        writer.add_message(
            EXPECTED_MESSAGE,
        )


def test_executor_creates_archive_conversation_and_message(
    tmp_path: Path,
) -> None:
    """
    Executor creates the canonical conversation and message on the
    destination.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    _create_archive(
        paths,
    )

    destination = FakeDestinationAdapter()

    with Archive(
        paths,
    ) as archive:

        result = OperationExecutor().execute(
            archive,
            destination,
        )

    assert destination.created_conversations == [
        EXPECTED_CONVERSATION,
    ]

    assert destination.created_messages == [
        EXPECTED_MESSAGE,
    ]

    assert result.conversations[
        EXPECTED_CONVERSATION.id
    ] == DestinationConversationRef(
        id=f"destination-{EXPECTED_CONVERSATION.id}",
    )

    assert result.messages[
        EXPECTED_MESSAGE.id
    ] == DestinationMessageRef(
        id=f"destination-{EXPECTED_MESSAGE.id}",
    )


def test_executor_creates_conversation_before_messages(
    tmp_path: Path,
) -> None:
    """
    Executor creates a conversation before creating messages belonging
    to that conversation.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    _create_archive(
        paths,
    )

    events = []

    class OrderedDestination(
        FakeDestinationAdapter,
    ):
        def create_conversation(
            self,
            conversation: CanonicalConversation,
        ) -> DestinationConversationRef:

            events.append(
                (
                    "conversation",
                    conversation.id,
                ),
            )

            return super().create_conversation(
                conversation,
            )

        def create_message(
            self,
            message: CanonicalMessage,
        ) -> DestinationMessageRef:

            events.append(
                (
                    "message",
                    message.id,
                ),
            )

            return super().create_message(
                message,
            )

    destination = OrderedDestination()

    with Archive(
        paths,
    ) as archive:
        OperationExecutor().execute(
            archive,
            destination,
        )

    assert events == [
        (
            "conversation",
            EXPECTED_CONVERSATION.id,
        ),
        (
            "message",
            EXPECTED_MESSAGE.id,
        ),
    ]