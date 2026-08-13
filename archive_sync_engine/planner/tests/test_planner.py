"""
Tests for the synchronization planner.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from datetime import timezone
from unittest.mock import Mock

import pytest

from archive_sync_engine.adapters import (
    CapabilityError,
    DestinationCapabilities,
)
from archive_sync_engine.archive import Archive
from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
    CanonicalReaction,
)
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.ids import (
    AttachmentId,
    ConversationId,
    IdentityKey,
    MessageId,
)
from archive_sync_engine.operations import (
    AddAttachmentOperation,
    AddReactionOperation,
    CreateConversationOperation,
    CreateIdentityOperation,
    DeleteIdentityOperation,
    CreateMessageOperation,
    DeleteConversationOperation,
    DeleteMessageOperation,
    EditMessageOperation,
    PinMessageOperation,
    RemoveAttachmentOperation,
    ReorderAttachmentsOperation,
    RemoveReactionOperation,
    SetMessageReplyOperation,
)
from archive_sync_engine.planner import Planner
from archive_sync_engine.sync import SynchronizationState
from archive_sync_engine.sync.fingerprint import (
    canonical_fingerprint,
    canonical_message_content_fingerprint,
)


def _archive() -> Mock:
    """
    Create a mock Archive.
    """

    return Mock(
        spec=Archive,
    )


def _capabilities(**overrides: bool) -> DestinationCapabilities:
    """
    Create destination capabilities for planner tests.
    """

    values = {
        "supports_threads": True,
        "supports_message_editing": True,
        "supports_message_deletion": True,
        "supports_conversation_deletion": True,
        "supports_message_pinning": True,
        "supports_reactions": True,
        "supports_custom_emoji": True,
        "supports_attachments": True,
        "supports_initial_message_attachments": False,
        "supports_attachment_reordering": True,
        "supports_replying": True,
        "supports_identity_updates": True,
        "supports_identity_deletion": True,
    }
    values.update(overrides)
    return DestinationCapabilities(**values)


def _identity(
    identity_key: str,
) -> CanonicalIdentity:
    """
    Create a canonical identity.
    """

    return CanonicalIdentity(
        identity_key=IdentityKey(
            identity_key,
        ),
        display_name=identity_key,
    )


def _conversation(
    conversation_id: str,
    *,
    conversation_type: ConversationType = ConversationType.CHANNEL,
    parent_id: str | None = None,
) -> CanonicalConversation:
    """
    Create a canonical conversation.
    """

    return CanonicalConversation(
        id=ConversationId(
            conversation_id,
        ),
        conversation_type=conversation_type,
        title=conversation_id,
        parent_id=(
            ConversationId(parent_id)
            if parent_id is not None
            else None
        ),
    )


def _message(
    message_id: str,
    conversation_id: str,
    identity_key: str = "identity-001",
) -> CanonicalMessage:
    """
    Create a canonical message.
    """

    return CanonicalMessage(
        id=MessageId(
            message_id,
        ),
        conversation_id=ConversationId(
            conversation_id,
        ),
        identity_key=IdentityKey(
            identity_key,
        ),
        content=f"Message {message_id}",
        created_at=datetime(
            2026,
            8,
            1,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )


def _attachment(
    attachment_id: str = "attachment-001",
    sha256: str = "a" * 64,
    filename: str = "example.txt",
) -> CanonicalAttachment:
    """Create a canonical attachment for planner tests."""

    return CanonicalAttachment(
        id=AttachmentId(attachment_id),
        filename=filename,
        content_type="text/plain",
        size=5,
        sha256=sha256,
    )


def _reaction(
    identity_key: str = "identity-002",
    emoji: str = "👍",
    emoji_id: str | None = None,
    is_custom: bool = False,
) -> CanonicalReaction:
    """
    Create a canonical reaction for planner tests.
    """

    return CanonicalReaction(
        identity_key=IdentityKey(identity_key),
        emoji=emoji,
        emoji_id=emoji_id,
        is_custom=is_custom,
    )


def _planned_operations(
    planner: Planner,
    archive: Archive,
    state: SynchronizationState | None = None,
    capabilities: DestinationCapabilities | None = None,
) -> list:
    """
    Materialize planner output for assertions.
    """

    if state is None:
        state = SynchronizationState()

    if capabilities is None:
        capabilities = _capabilities()

    return list(
        planner.plan(
            archive=archive,
            synchronization_state=state,
            capabilities=capabilities,
        ),
    )



def test_plan_messages_reconciles_attachment_reordering() -> None:
    archive = _archive()
    message = _message("message-001", "conversation-001")
    first = _attachment("attachment-001", "1" * 64, "first.txt")
    second = _attachment("attachment-002", "2" * 64, "second.txt")
    current = replace(message, attachments=(second, first))

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([current])

    state = SynchronizationState(
        messages={"message-001": Mock()},
        message_fingerprints={"message-001": canonical_fingerprint(message)},
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": (first, second)},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    operations = list(Planner().plan(archive, state, _capabilities()))

    assert operations == [
        ReorderAttachmentsOperation(
            message_id=MessageId("message-001"),
            attachments=(second, first),
            canonical_fingerprint=canonical_fingerprint(current),
        ),
    ]


def test_plan_messages_rejects_unsupported_attachment_reordering() -> None:
    archive = _archive()
    message = _message("message-001", "conversation-001")
    first = _attachment("attachment-001", "1" * 64, "first.txt")
    second = _attachment("attachment-002", "2" * 64, "second.txt")
    current = replace(message, attachments=(second, first))

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([current])

    state = SynchronizationState(
        messages={"message-001": Mock()},
        message_fingerprints={"message-001": canonical_fingerprint(message)},
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": (first, second)},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    with pytest.raises(CapabilityError, match="supports_attachment_reordering"):
        list(Planner().plan(archive, state, _capabilities(
            supports_attachment_reordering=False,
        )))


def test_plan_creates_identities_before_conversations_and_messages() -> None:
    archive = _archive()

    identity = _identity(
        "identity-001",
    )

    conversation = _conversation(
        "conversation-001",
    )

    message = _message(
        "message-001",
        "conversation-001",
    )

    archive.iter_identities.return_value = iter(
        [
            identity,
        ],
    )

    archive.iter_conversations.return_value = iter(
        [
            conversation,
        ],
    )

    archive.iter_messages.return_value = iter(
        [
            message,
        ],
    )

    operations = _planned_operations(
        Planner(),
        archive,
    )

    assert operations == [
        CreateConversationOperation(
            conversation=conversation,
        ),
        CreateIdentityOperation(
            identity=identity,
        ),
        CreateMessageOperation(
            message=message,
        ),
    ]


def test_plan_skips_already_synchronized_entities() -> None:
    archive = _archive()

    identity = _identity(
        "identity-001",
    )

    conversation = _conversation(
        "conversation-001",
    )

    message = _message(
        "message-001",
        "conversation-001",
    )

    archive.iter_identities.return_value = iter(
        [
            identity,
        ],
    )

    archive.iter_conversations.return_value = iter(
        [
            conversation,
        ],
    )

    archive.iter_messages.return_value = iter(
        [
            message,
        ],
    )

    state = SynchronizationState(
        identities={
            "identity-001": Mock(),
        },
        conversations={
            "conversation-001": Mock(),
        },
        messages={
            "message-001": Mock(),
        },
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={
            "conversation-001": None,
        },
        identity_fingerprints={
            "identity-001": canonical_fingerprint(identity),
        },
        message_fingerprints={
            "message-001": canonical_fingerprint(message),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={
            "message-001": (),
        },
        message_attachments={
            "message-001": (),
        },
        message_pinned={
            "message-001": False,
        },
        message_reply_to={
            "message-001": None,
        },
    )

    operations = _planned_operations(
        Planner(),
        archive,
        state,
    )

    assert operations == []


def test_plan_creates_parent_conversation_before_thread() -> None:
    archive = _archive()

    parent = _conversation(
        "conversation-001",
    )

    thread = _conversation(
        "thread-001",
        conversation_type=ConversationType.THREAD,
        parent_id="conversation-001",
    )

    archive.iter_identities.return_value = iter(
        []

    )

    archive.iter_conversations.return_value = iter(
        [
            thread,
            parent,
        ],
    )

    archive.iter_messages.return_value = iter(
        []
    )

    operations = _planned_operations(
        Planner(),
        archive,
    )

    assert operations == [
        CreateConversationOperation(
            conversation=parent,
        ),
        CreateConversationOperation(
            conversation=thread,
        ),
    ]


def test_plan_does_not_duplicate_parent_conversation() -> None:
    archive = _archive()

    parent = _conversation(
        "conversation-001",
    )

    first_thread = _conversation(
        "thread-001",
        conversation_type=ConversationType.THREAD,
        parent_id="conversation-001",
    )

    second_thread = _conversation(
        "thread-002",
        conversation_type=ConversationType.THREAD,
        parent_id="conversation-001",
    )

    archive.iter_identities.return_value = iter(
        []
    )

    archive.iter_conversations.return_value = iter(
        [
            first_thread,
            second_thread,
            parent,
        ],
    )

    archive.iter_messages.return_value = iter(
        []
    )

    operations = _planned_operations(
        Planner(),
        archive,
    )

    assert operations == [
        CreateConversationOperation(
            conversation=parent,
        ),
        CreateConversationOperation(
            conversation=first_thread,
        ),
        CreateConversationOperation(
            conversation=second_thread,
        ),
    ]


def test_plan_raises_when_thread_parent_is_missing() -> None:
    archive = _archive()

    thread = _conversation(
        "thread-001",
        conversation_type=ConversationType.THREAD,
        parent_id="missing-parent",
    )

    archive.iter_identities.return_value = iter(
        []
    )

    archive.iter_conversations.return_value = iter(
        [
            thread,
        ],
    )

    planner = Planner()

    with pytest.raises(
        RuntimeError,
        match=(
            "references missing parent conversation "
            "missing-parent"
        ),
    ):
        list(
            planner.plan(
                archive=archive,
                synchronization_state=SynchronizationState(),
                capabilities=_capabilities(),
            ),
        )


def test_plan_raises_when_conversation_hierarchy_is_circular() -> None:
    archive = _archive()

    first = _conversation(
        "conversation-001",
        conversation_type=ConversationType.THREAD,
        parent_id="conversation-002",
    )

    second = _conversation(
        "conversation-002",
        conversation_type=ConversationType.THREAD,
        parent_id="conversation-001",
    )

    archive.iter_identities.return_value = iter(
        []
    )

    archive.iter_conversations.return_value = iter(
        [
            first,
            second,
        ],
    )

    planner = Planner()

    with pytest.raises(
        RuntimeError,
        match="Circular conversation parent relationship detected",
    ):
        list(
            planner.plan(
                archive=archive,
                synchronization_state=SynchronizationState(),
                capabilities=_capabilities(),
            ),
        )


def test_plan_messages_preserves_archive_conversation_order() -> None:
    archive = _archive()

    first_conversation = _conversation(
        "conversation-001",
    )

    second_conversation = _conversation(
        "conversation-002",
    )

    first_message = _message(
        "message-001",
        "conversation-001",
    )

    second_message = _message(
        "message-002",
        "conversation-002",
    )

    archive.iter_identities.return_value = iter(
        []
    )

    archive.iter_conversations.return_value = iter(
        [
            first_conversation,
            second_conversation,
        ],
    )

    archive.iter_messages.return_value = iter(
        [
            first_message,
            second_message,
        ],
    )

    operations = _planned_operations(
        Planner(),
        archive,
    )

    assert operations == [
        CreateConversationOperation(
            conversation=first_conversation,
        ),
        CreateConversationOperation(
            conversation=second_conversation,
        ),
        CreateMessageOperation(
            message=first_message,
        ),
        CreateMessageOperation(
            message=second_message,
        ),
    ]


def test_plan_message_unchanged_attachments_produce_no_attachment_operation() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    attachment = _attachment()
    message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=ConversationId("conversation-001"),
        identity_key=IdentityKey("identity-001"),
        content="Message message-001",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
        attachments=(attachment,),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={"message-001": canonical_fingerprint(message)},
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": (attachment,)},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    operations = _planned_operations(Planner(), archive, state)

    assert operations == []


def test_plan_attachment_order_change_uses_reorder_operation() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    first = _attachment("attachment-001", "a" * 64, "first.txt")
    second = _attachment("attachment-002", "b" * 64, "second.txt")
    message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=ConversationId("conversation-001"),
        identity_key=IdentityKey("identity-001"),
        content="Message message-001",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
        attachments=(first, second),
    )
    desired_message = replace(
        message,
        attachments=(second, first),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={"message-001": canonical_fingerprint(message)},
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": (first, second)},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    operations = list(
        Planner().plan(
            archive=archive,
            synchronization_state=state,
            capabilities=_capabilities(),
        ),
    )

    assert operations == [
        ReorderAttachmentsOperation(
            message_id=MessageId("message-001"),
            attachments=(second, first),
            canonical_fingerprint=canonical_fingerprint(desired_message),
        ),
    ]


def test_plan_message_attachment_addition_uses_attachment_operation() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    attachment = _attachment()
    message = _message("message-001", "conversation-001")
    desired_message = CanonicalMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content=message.content,
        created_at=message.created_at,
        attachments=(attachment,),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={
            "message-001": canonical_fingerprint(message),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    operations = _planned_operations(Planner(), archive, state)

    assert operations == [
        AddAttachmentOperation(
            message_id=desired_message.id,
            attachment=attachment,
            resulting_attachments=(attachment,),
            canonical_fingerprint=canonical_fingerprint(desired_message),
        ),
    ]


def test_plan_message_attachment_removal_uses_attachment_operation() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    attachment = _attachment()
    message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=ConversationId("conversation-001"),
        identity_key=IdentityKey("identity-001"),
        content="Message message-001",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
        attachments=(attachment,),
    )
    desired_message = _message("message-001", "conversation-001")

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={
            "message-001": canonical_fingerprint(message),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": (attachment,)},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    operations = _planned_operations(Planner(), archive, state)

    assert operations == [
        RemoveAttachmentOperation(
            message_id=desired_message.id,
            attachment=attachment,
            resulting_attachments=(),
            canonical_fingerprint=canonical_fingerprint(desired_message),
        ),
    ]


def test_plan_attachment_change_does_not_use_edit_operation() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    attachment = _attachment()
    message = _message("message-001", "conversation-001")
    desired_message = CanonicalMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content=message.content,
        created_at=message.created_at,
        attachments=(attachment,),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={
            "message-001": canonical_fingerprint(message),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    operations = _planned_operations(Planner(), archive, state)

    assert all(
        not isinstance(operation, EditMessageOperation)
        for operation in operations
    )


def test_plan_rejects_unsupported_attachment_reconciliation() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    attachment = _attachment()
    message = _message("message-001", "conversation-001")
    desired_message = CanonicalMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content=message.content,
        created_at=message.created_at,
        attachments=(attachment,),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={
            "message-001": canonical_fingerprint(message),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    capabilities = DestinationCapabilities(
        supports_attachments=False,
        supports_identity_updates=True,
    )

    with pytest.raises(CapabilityError, match="supports_attachments"):
        list(
            Planner().plan(
                archive=archive,
                synchronization_state=state,
                capabilities=capabilities,
            ),
        )


def test_plan_message_reaction_change_uses_reaction_operations() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    reaction = _reaction()
    message = _message("message-001", "conversation-001")
    desired_message = CanonicalMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content=message.content,
        created_at=message.created_at,
        destination_id=message.destination_id,
        edited_at=message.edited_at,
        reply_to=message.reply_to,
        pinned=message.pinned,
        attachments=message.attachments,
        reactions=(reaction,),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={
            "message-001": canonical_fingerprint(message),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    operations = _planned_operations(Planner(), archive, state)

    assert operations == [
        AddReactionOperation(
            message_id=desired_message.id,
            reaction=reaction,
            resulting_reactions=(reaction,),
            canonical_fingerprint=canonical_fingerprint(desired_message),
        ),
    ]


def test_plan_message_pin_change_uses_pin_operation() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    message = _message("message-001", "conversation-001")
    desired_message = CanonicalMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content=message.content,
        created_at=message.created_at,
        destination_id=message.destination_id,
        edited_at=message.edited_at,
        reply_to=message.reply_to,
        pinned=True,
        attachments=message.attachments,
        reactions=message.reactions,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={
            "message-001": canonical_fingerprint(message),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    operations = _planned_operations(Planner(), archive, state)

    assert operations == [
        PinMessageOperation(
            message_id=desired_message.id,
            canonical_fingerprint=canonical_fingerprint(desired_message),
        ),
    ]


def test_plan_message_content_change_uses_edit_operation() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    message = _message("message-001", "conversation-001")
    desired_message = CanonicalMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content="Changed content",
        created_at=message.created_at,
        destination_id=message.destination_id,
        edited_at=message.edited_at,
        reply_to=message.reply_to,
        pinned=message.pinned,
        attachments=message.attachments,
        reactions=message.reactions,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={
            "message-001": canonical_fingerprint(message),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    operations = _planned_operations(Planner(), archive, state)

    assert operations == [
        EditMessageOperation(
            message=desired_message,
            canonical_fingerprint=canonical_fingerprint(desired_message),
        ),
    ]


def _state_for_message(
    message: CanonicalMessage,
    *,
    reactions: tuple[CanonicalReaction, ...],
) -> SynchronizationState:
    conversation = _conversation(str(message.conversation_id))
    return SynchronizationState(
        conversations={str(conversation.id): Mock()},
        conversation_fingerprints={
            str(conversation.id): canonical_fingerprint(conversation),
        },
        conversation_parent_ids={str(conversation.id): None},
        messages={str(message.id): Mock()},
        message_fingerprints={
            str(message.id): canonical_fingerprint(
                replace(message, reactions=reactions),
            ),
        },
        message_content_fingerprints={
            str(message.id): canonical_message_content_fingerprint(
                replace(message, reactions=reactions),
            ),
        },
        message_reactions={str(message.id): reactions},
        message_attachments={str(message.id): ()},
        message_pinned={str(message.id): message.pinned},
        message_reply_to={str(message.id): message.reply_to},
    )


def test_plan_custom_emoji_addition_requires_custom_emoji_capability() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    reaction = _reaction(
        emoji=":blob:",
        emoji_id="emoji-001",
        is_custom=True,
    )
    old_message = _message("message-001", "conversation-001")
    desired_message = replace(old_message, reactions=(reaction,))
    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])
    state = _state_for_message(old_message, reactions=())

    with pytest.raises(CapabilityError, match="supports_custom_emoji"):
        list(
            Planner().plan(
                archive,
                state,
                _capabilities(supports_custom_emoji=False),
            ),
        )


def test_plan_custom_emoji_removal_requires_custom_emoji_capability() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    reaction = _reaction(
        emoji=":blob:",
        emoji_id="emoji-001",
        is_custom=True,
    )
    desired_message = _message("message-001", "conversation-001")
    old_message = replace(desired_message, reactions=(reaction,))
    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])
    state = _state_for_message(old_message, reactions=(reaction,))

    with pytest.raises(CapabilityError, match="supports_custom_emoji"):
        list(
            Planner().plan(
                archive,
                state,
                _capabilities(supports_custom_emoji=False),
            ),
        )


def test_plan_custom_emoji_reconciliation_is_allowed_when_supported() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    reaction = _reaction(
        emoji=":blob:",
        emoji_id="emoji-001",
        is_custom=True,
    )
    old_message = _message("message-001", "conversation-001")
    desired_message = replace(old_message, reactions=(reaction,))
    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])
    state = _state_for_message(old_message, reactions=())

    operations = list(
        Planner().plan(
            archive,
            state,
            _capabilities(supports_custom_emoji=True),
        ),
    )

    assert operations == [
        AddReactionOperation(
            message_id=desired_message.id,
            reaction=reaction,
            resulting_reactions=(reaction,),
            canonical_fingerprint=canonical_fingerprint(desired_message),
        ),
    ]


def test_plan_message_changes_decompose_content_reaction_and_pin() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    old_reaction = _reaction(emoji="👍")
    new_reaction = _reaction(emoji="❤️")
    message = _message("message-001", "conversation-001")
    message = CanonicalMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content=message.content,
        created_at=message.created_at,
        pinned=False,
        reactions=(old_reaction,),
    )
    desired_message = CanonicalMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content="Changed content",
        created_at=message.created_at,
        pinned=True,
        reactions=(new_reaction,),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={
            "message-001": canonical_fingerprint(message),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": (old_reaction,)},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    operations = _planned_operations(Planner(), archive, state)

    assert operations == [
        EditMessageOperation(
            message=desired_message,
        ),
        RemoveReactionOperation(
            message_id=desired_message.id,
            reaction=old_reaction,
            resulting_reactions=(),
        ),
        AddReactionOperation(
            message_id=desired_message.id,
            reaction=new_reaction,
            resulting_reactions=(new_reaction,),
        ),
        PinMessageOperation(
            message_id=desired_message.id,
            canonical_fingerprint=canonical_fingerprint(desired_message),
        ),
    ]


def test_build_plan_materializes_operations() -> None:
    archive = _archive()

    conversation = _conversation(
        "conversation-001",
    )

    archive.iter_identities.return_value = iter(
        []
    )

    archive.iter_conversations.return_value = iter(
        [
            conversation,
        ],
    )

    archive.iter_messages.return_value = iter(
        []
    )

    plan = Planner().build_plan(
        archive=archive,
        synchronization_state=SynchronizationState(),
        capabilities=_capabilities(),
    )

    assert len(plan) == 1
    assert bool(plan)

    assert list(plan) == [
        CreateConversationOperation(
            conversation=conversation,
        ),
    ]

def test_plan_deletes_stale_replying_message_before_stale_reply_target() -> None:
    archive = _archive()
    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([])

    state = SynchronizationState(
        messages={
            "message-parent": Mock(),
            "message-reply": Mock(),
        },
        message_reply_to={
            "message-parent": None,
            "message-reply": MessageId("message-parent"),
        },
    )

    operations = _planned_operations(Planner(), archive, state)

    assert operations == [
        DeleteMessageOperation(
            message_id=MessageId("message-reply"),
        ),
        DeleteMessageOperation(
            message_id=MessageId("message-parent"),
        ),
    ]


def test_plan_rejects_circular_stale_message_reply_relationship() -> None:
    archive = _archive()
    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([])

    state = SynchronizationState(
        messages={
            "message-001": Mock(),
            "message-002": Mock(),
        },
        message_reply_to={
            "message-001": MessageId("message-002"),
            "message-002": MessageId("message-001"),
        },
    )

    with pytest.raises(
        RuntimeError,
        match="Circular synchronization-state message reply relationship",
    ):
        _planned_operations(Planner(), archive, state)


def test_plan_deletes_stale_messages_before_stale_conversations() -> None:
    archive = _archive()

    conversation = _conversation(
        "conversation-001",
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([])

    state = SynchronizationState(
        conversations={
            "conversation-001": Mock(),
            "conversation-stale": Mock(),
        },
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
            "conversation-stale": "stale-fingerprint",
        },
        conversation_parent_ids={
            "conversation-001": None,
            "conversation-stale": None,
        },
        messages={
            "message-stale": Mock(),
        },
        message_fingerprints={
            "message-stale": "stale-fingerprint",
        },
    )

    operations = _planned_operations(
        Planner(),
        archive,
        state,
    )

    assert operations == [
        DeleteMessageOperation(
            message_id="message-stale",
        ),
        DeleteConversationOperation(
            conversation_id="conversation-stale",
        ),
    ]


def test_plan_deletes_stale_child_conversation_before_parent() -> None:
    archive = _archive()

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([])

    state = SynchronizationState(
        conversations={
            "parent": Mock(),
            "child": Mock(),
        },
        conversation_fingerprints={
            "parent": "parent-fingerprint",
            "child": "child-fingerprint",
        },
        conversation_parent_ids={
            "parent": None,
            "child": "parent",
        },
    )

    operations = _planned_operations(
        Planner(),
        archive,
        state,
    )

    assert operations == [
        DeleteConversationOperation(
            conversation_id="child",
        ),
        DeleteConversationOperation(
            conversation_id="parent",
        ),
    ]


def test_plan_raises_when_stale_conversation_parent_metadata_is_missing() -> None:
    archive = _archive()

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([])

    state = SynchronizationState(
        conversations={
            "conversation-stale": Mock(),
        },
        conversation_fingerprints={
            "conversation-stale": "fingerprint",
        },
    )

    with pytest.raises(
        RuntimeError,
        match="missing the parent relationship",
    ):
        _planned_operations(
            Planner(),
            archive,
            state,
        )


def test_plan_rejects_unsupported_message_editing() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    message = _message("message-001", "conversation-001")
    desired_message = CanonicalMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content="Changed content",
        created_at=message.created_at,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={"message-001": canonical_fingerprint(message)},
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    capabilities = DestinationCapabilities(
        supports_message_editing=False,
        supports_reactions=True,
        supports_message_pinning=True,
        supports_message_deletion=True,
        supports_conversation_deletion=True,
        supports_identity_updates=True,
        supports_threads=True,
    )

    with pytest.raises(CapabilityError, match="supports_message_editing"):
        list(
            Planner().plan(
                archive=archive,
                synchronization_state=state,
                capabilities=capabilities,
            ),
        )


def test_plan_rejects_unsupported_reactions() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    reaction = _reaction()
    message = _message("message-001", "conversation-001")
    desired_message = CanonicalMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content=message.content,
        created_at=message.created_at,
        reactions=(reaction,),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={"message-001": canonical_fingerprint(message)},
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    capabilities = DestinationCapabilities(
        supports_message_editing=True,
        supports_reactions=False,
        supports_message_pinning=True,
        supports_message_deletion=True,
        supports_conversation_deletion=True,
        supports_identity_updates=True,
        supports_threads=True,
    )

    with pytest.raises(CapabilityError, match="supports_reactions"):
        list(
            Planner().plan(
                archive=archive,
                synchronization_state=state,
                capabilities=capabilities,
            ),
        )


def test_plan_rejects_unsupported_message_pinning() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    message = _message("message-001", "conversation-001")
    desired_message = CanonicalMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content=message.content,
        created_at=message.created_at,
        pinned=True,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([desired_message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={"message-001": canonical_fingerprint(message)},
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    capabilities = DestinationCapabilities(
        supports_message_editing=True,
        supports_reactions=True,
        supports_message_pinning=False,
        supports_message_deletion=True,
        supports_conversation_deletion=True,
        supports_identity_updates=True,
        supports_threads=True,
    )

    with pytest.raises(CapabilityError, match="supports_message_pinning"):
        list(
            Planner().plan(
                archive=archive,
                synchronization_state=state,
                capabilities=capabilities,
            ),
        )


def test_plan_rejects_unsupported_message_deletion() -> None:
    archive = _archive()
    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([])

    state = SynchronizationState(
        messages={"message-stale": Mock()},
        message_fingerprints={"message-stale": "fingerprint"},
        message_content_fingerprints={"message-stale": "content"},
        message_reactions={"message-stale": ()},
        message_pinned={"message-stale": False},
    )

    capabilities = DestinationCapabilities(
        supports_message_deletion=False,
        supports_identity_updates=True,
        supports_threads=True,
    )

    with pytest.raises(CapabilityError, match="supports_message_deletion"):
        list(
            Planner().plan(
                archive=archive,
                synchronization_state=state,
                capabilities=capabilities,
            ),
        )



def test_plan_rejects_unsupported_conversation_deletion() -> None:
    archive = _archive()

    conversation = _conversation("conversation-001")

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
    )

    capabilities = _capabilities()
    capabilities = DestinationCapabilities(
        supports_threads=capabilities.supports_threads,
        supports_message_editing=capabilities.supports_message_editing,
        supports_message_deletion=capabilities.supports_message_deletion,
        supports_conversation_deletion=False,
        supports_message_pinning=capabilities.supports_message_pinning,
        supports_reactions=capabilities.supports_reactions,
        supports_custom_emoji=capabilities.supports_custom_emoji,
        supports_attachments=capabilities.supports_attachments,
        supports_replying=capabilities.supports_replying,
        supports_identity_updates=capabilities.supports_identity_updates,
    )

    with pytest.raises(
        CapabilityError,
        match="supports_conversation_deletion",
    ):
        _planned_operations(
            Planner(),
            archive,
            state,
            capabilities=capabilities,
        )

def test_plan_rejects_unsupported_identity_updates() -> None:
    archive = _archive()
    identity = _identity("identity-001")
    desired_identity = CanonicalIdentity(
        identity_key=identity.identity_key,
        display_name="Changed identity",
    )

    archive.iter_identities.return_value = iter([desired_identity])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([])

    state = SynchronizationState(
        identities={"identity-001": Mock()},
        identity_fingerprints={
            "identity-001": canonical_fingerprint(identity),
        },
    )

    capabilities = DestinationCapabilities(
        supports_identity_updates=False,
        supports_threads=True,
    )

    with pytest.raises(CapabilityError, match="supports_identity_updates"):
        list(
            Planner().plan(
                archive=archive,
                synchronization_state=state,
                capabilities=capabilities,
            ),
        )


def test_plan_rejects_unsupported_thread_creation() -> None:
    archive = _archive()
    thread = _conversation(
        "thread-001",
        conversation_type=ConversationType.THREAD,
        parent_id="conversation-001",
    )
    parent = _conversation("conversation-001")

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([thread, parent])
    archive.iter_messages.return_value = iter([])

    capabilities = DestinationCapabilities(
        supports_threads=False,
        supports_identity_updates=True,
    )

    with pytest.raises(CapabilityError, match="supports_threads"):
        list(
            Planner().plan(
                archive=archive,
                synchronization_state=SynchronizationState(),
                capabilities=capabilities,
            ),
        )


def test_plan_rejects_unsupported_thread_update() -> None:
    archive = _archive()
    parent = _conversation("conversation-001")
    thread = _conversation(
        "thread-001",
        conversation_type=ConversationType.THREAD,
        parent_id="conversation-001",
    )
    updated_thread = CanonicalConversation(
        id=thread.id,
        conversation_type=thread.conversation_type,
        title="Updated thread title",
        parent_id=thread.parent_id,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([parent, updated_thread])
    archive.iter_messages.return_value = iter([])

    state = SynchronizationState(
        conversations={
            "conversation-001": Mock(),
            "thread-001": Mock(),
        },
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(parent),
            "thread-001": canonical_fingerprint(thread),
        },
        conversation_parent_ids={
            "conversation-001": None,
            "thread-001": "conversation-001",
        },
    )

    capabilities = DestinationCapabilities(
        supports_threads=False,
        supports_identity_updates=True,
    )

    with pytest.raises(CapabilityError, match="supports_threads"):
        list(
            Planner().plan(
                archive=archive,
                synchronization_state=state,
                capabilities=capabilities,
            ),
        )


def test_plan_validates_all_capabilities_before_yielding_operations() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    updated_conversation = CanonicalConversation(
        id=conversation.id,
        conversation_type=conversation.conversation_type,
        title="Updated conversation title",
        parent_id=conversation.parent_id,
    )
    message = _message("message-001", "conversation-001")
    updated_message = CanonicalMessage(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content="Updated message content",
        created_at=message.created_at,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([updated_conversation])
    archive.iter_messages.return_value = iter([updated_message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={
            "message-001": canonical_fingerprint(message),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    capabilities = DestinationCapabilities(
        supports_message_editing=False,
        supports_message_deletion=True,
        supports_conversation_deletion=True,
        supports_message_pinning=True,
        supports_reactions=True,
        supports_identity_updates=True,
        supports_threads=True,
    )

    operations = Planner().plan(
        archive=archive,
        synchronization_state=state,
        capabilities=capabilities,
    )

    with pytest.raises(CapabilityError, match="supports_message_editing"):
        next(operations)


def test_plan_message_reply_change_uses_reply_operation() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    target = _message("message-002", "conversation-001")
    message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=ConversationId("conversation-001"),
        identity_key=IdentityKey("identity-001"),
        content="Message message-001",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
        reply_to=target.id,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([target, message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={
            "message-001": Mock(),
            "message-002": Mock(),
        },
        message_fingerprints={
            "message-001": canonical_fingerprint(
                replace(message, reply_to=None),
            ),
            "message-002": canonical_fingerprint(target),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
            "message-002": canonical_message_content_fingerprint(target),
        },
        message_reactions={"message-001": (), "message-002": ()},
        message_attachments={"message-001": (), "message-002": ()},
        message_pinned={"message-001": False, "message-002": False},
        message_reply_to={"message-001": None, "message-002": None},
    )

    operations = _planned_operations(Planner(), archive, state)

    assert operations == [
        SetMessageReplyOperation(
            message_id=message.id,
            reply_to=target.id,
            canonical_fingerprint=canonical_fingerprint(message),
        ),
    ]


def test_plan_new_reply_message_defers_reply_until_after_message_creations() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    target = _message("message-002", "conversation-001")
    message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=ConversationId("conversation-001"),
        identity_key=IdentityKey("identity-001"),
        content="Message message-001",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
        reply_to=target.id,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([message, target])

    operations = _planned_operations(Planner(), archive)

    assert operations == [
        CreateConversationOperation(conversation=conversation),
        CreateMessageOperation(message=message),
        CreateMessageOperation(message=target),
        SetMessageReplyOperation(
            message_id=message.id,
            reply_to=target.id,
            canonical_fingerprint=canonical_fingerprint(message),
        ),
    ]


def test_plan_rejects_reply_to_missing_archive_message() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    target = _message("message-missing", "conversation-001")
    message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=ConversationId("conversation-001"),
        identity_key=IdentityKey("identity-001"),
        content="Message message-001",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
        reply_to=target.id,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([message])

    with pytest.raises(RuntimeError, match="not present in the canonical Archive"):
        list(Planner().plan(
            archive=archive,
            synchronization_state=SynchronizationState(),
            capabilities=_capabilities(),
        ))


def test_plan_rejects_unsupported_replying() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    target = _message("message-002", "conversation-001")
    message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=ConversationId("conversation-001"),
        identity_key=IdentityKey("identity-001"),
        content="Message message-001",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
        reply_to=target.id,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([message, target])

    capabilities = _capabilities()
    capabilities = replace(capabilities, supports_replying=False)

    with pytest.raises(CapabilityError, match="supports_replying"):
        list(Planner().plan(
            archive=archive,
            synchronization_state=SynchronizationState(),
            capabilities=capabilities,
        ))


def test_plan_message_unreply_uses_reply_operation_and_finalizes_fingerprint() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    target = _message("message-002", "conversation-001")
    message = _message("message-001", "conversation-001")
    old_message = replace(message, reply_to=target.id)

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([target, message])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock(), "message-002": Mock()},
        message_fingerprints={
            "message-001": canonical_fingerprint(old_message),
            "message-002": canonical_fingerprint(target),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(old_message),
            "message-002": canonical_message_content_fingerprint(target),
        },
        message_reactions={"message-001": (), "message-002": ()},
        message_attachments={"message-001": (), "message-002": ()},
        message_pinned={"message-001": False, "message-002": False},
        message_reply_to={"message-001": target.id, "message-002": None},
    )

    operations = _planned_operations(Planner(), archive, state)

    assert operations == [
        SetMessageReplyOperation(
            message_id=message.id,
            reply_to=None,
            canonical_fingerprint=canonical_fingerprint(message),
        ),
    ]


def test_message_reply_is_not_part_of_content_fingerprint() -> None:
    message = _message("message-001", "conversation-001")
    reply = _message("message-002", "conversation-001")

    assert canonical_message_content_fingerprint(message) == (
        canonical_message_content_fingerprint(
            replace(message, reply_to=reply.id),
        )
    )


def test_plan_deletes_stale_identity_after_messages_and_conversations() -> None:
    archive = _archive()
    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([])

    state = SynchronizationState(
        identities={"identity-001": Mock()},
        identity_fingerprints={"identity-001": "fingerprint"},
    )

    operations = _planned_operations(Planner(), archive, state)

    assert operations == [
        DeleteIdentityOperation(
            identity_key=IdentityKey("identity-001"),
        ),
    ]


def test_plan_deletes_stale_identity_after_stale_messages_and_conversations() -> None:
    archive = _archive()
    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([])

    state = SynchronizationState(
        identities={"identity-001": Mock()},
        identity_fingerprints={"identity-001": "identity-fingerprint"},
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={"conversation-001": "conversation-fingerprint"},
        conversation_parent_ids={"conversation-001": None},
        messages={"message-001": Mock()},
        message_fingerprints={"message-001": "message-fingerprint"},
        message_content_fingerprints={"message-001": "content-fingerprint"},
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    operations = _planned_operations(Planner(), archive, state)

    assert operations == [
        DeleteMessageOperation(
            message_id=MessageId("message-001"),
        ),
        DeleteConversationOperation(
            conversation_id=ConversationId("conversation-001"),
        ),
        DeleteIdentityOperation(
            identity_key=IdentityKey("identity-001"),
        ),
    ]


def test_plan_rejects_unsupported_identity_deletion() -> None:
    archive = _archive()
    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([])

    state = SynchronizationState(
        identities={"identity-001": Mock()},
        identity_fingerprints={"identity-001": "fingerprint"},
    )

    with pytest.raises(
        CapabilityError,
        match="supports_identity_deletion",
    ):
        list(
            Planner().plan(
                archive=archive,
                synchronization_state=state,
                capabilities=_capabilities(
                    supports_identity_deletion=False,
                ),
            ),
        )


def test_plan_rejects_stale_identity_referenced_by_canonical_message() -> None:
    archive = _archive()
    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([
        _message("message-001", "conversation-001"),
    ])

    state = SynchronizationState(
        identities={"identity-001": Mock()},
        identity_fingerprints={"identity-001": "fingerprint"},
    )

    with pytest.raises(
        RuntimeError,
        match="missing from the Archive identity set",
    ):
        list(
            Planner().plan(
                archive=archive,
                synchronization_state=state,
                capabilities=_capabilities(),
            ),
        )


def test_plan_new_message_decomposes_initial_components() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    attachment = _attachment()
    reaction = _reaction()
    message = replace(
        _message("message-001", "conversation-001"),
        attachments=(attachment,),
        reactions=(reaction,),
        pinned=True,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([message])

    operations = _planned_operations(Planner(), archive)

    assert operations == [
        CreateConversationOperation(conversation=conversation),
        CreateMessageOperation(message=message),
        AddAttachmentOperation(
            message_id=message.id,
            attachment=attachment,
            resulting_attachments=(attachment,),
        ),
        AddReactionOperation(
            message_id=message.id,
            reaction=reaction,
            resulting_reactions=(reaction,),
        ),
        PinMessageOperation(
            message_id=message.id,
            canonical_fingerprint=canonical_fingerprint(message),
        ),
    ]


def test_plan_new_message_attachment_requires_attachment_capability() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    message = replace(
        _message("message-001", "conversation-001"),
        attachments=(_attachment(),),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([message])

    with pytest.raises(
        CapabilityError,
        match="supports_attachments",
    ):
        _planned_operations(
            Planner(),
            archive,
            capabilities=_capabilities(supports_attachments=False),
        )


def test_plan_does_not_reconcile_already_ordered_attachments() -> None:
    archive = _archive()

    conversation = _conversation("conversation-001")
    attachment_a = _attachment()
    attachment_b = replace(
        attachment_a,
        id=type(attachment_a.id)("attachment-002"),
        filename="second.txt",
        sha256="b" * 64,
    )

    message = replace(
        _message("message-001", "conversation-001"),
        attachments=(attachment_a, attachment_b),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([message])

    state = SynchronizationState(
        conversations={
            "conversation-001": Mock(),
        },
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        messages={
            "message-001": Mock(),
        },
        message_fingerprints={
            "message-001": canonical_fingerprint(message),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_attachments={
            "message-001": (
                attachment_a,
                attachment_b,
            ),
        },
        message_reactions={
            "message-001": (),
        },
        message_pinned={
            "message-001": False,
        },
        message_reply_to={
            "message-001": None,
        },
    )

    operations = _planned_operations(
        Planner(),
        archive,
        state,
    )

    assert operations == []


def test_plan_reconciles_attachment_and_reaction_changes_together() -> None:
    archive = _archive()

    conversation = _conversation("conversation-001")

    old_attachment = _attachment()

    new_attachment = replace(
        old_attachment,
        id=type(old_attachment.id)("attachment-002"),
        filename="new.txt",
        sha256="b" * 64,
    )

    old_reaction = _reaction()

    new_reaction = replace(
        old_reaction,
        emoji="🔥",
    )

    message = replace(
        _message("message-001", "conversation-001"),
        attachments=(new_attachment,),
        reactions=(new_reaction,),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([message])

    state = SynchronizationState(
        conversations={
            "conversation-001": Mock(),
        },
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        messages={
            "message-001": Mock(),
        },
        message_fingerprints={
            "message-001": "old-message-fingerprint",
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(message),
        },
        message_reactions={
            "message-001": (old_reaction,),
        },
        message_attachments={
            "message-001": (old_attachment,),
        },
        message_pinned={
            "message-001": False,
        },
        message_reply_to={
            "message-001": None,
        },
    )

    operations = _planned_operations(
        Planner(),
        archive,
        state,
    )

    assert len(operations) == 4

    assert operations[0].reaction == old_reaction
    assert operations[1].reaction == new_reaction
    assert operations[2].attachment == old_attachment
    assert operations[3].attachment == new_attachment


def test_plan_rejects_mixed_message_changes_before_exposing_any_operations() -> None:
    """Capability validation covers a complete decomposed message plan atomically."""
    archive = _archive()
    conversation = _conversation("conversation-001")
    reply_target = _message("message-000", "conversation-001")
    old_attachment = _attachment()
    new_attachment = replace(
        old_attachment,
        id=type(old_attachment.id)("attachment-002"),
        filename="new.txt",
        sha256="b" * 64,
    )
    old_reaction = _reaction()
    new_reaction = replace(
        old_reaction,
        emoji="🔥",
    )
    message = replace(
        _message("message-001", "conversation-001"),
        content="changed",
        reply_to=reply_target.id,
        attachments=(new_attachment,),
        reactions=(new_reaction,),
        pinned=True,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([reply_target, message])

    state = SynchronizationState(
        conversations={
            "conversation-001": Mock(),
        },
        conversation_fingerprints={
            "conversation-001": canonical_fingerprint(conversation),
        },
        conversation_parent_ids={
            "conversation-001": None,
        },
        messages={
            "message-001": Mock(),
            "message-000": Mock(),
        },
        message_fingerprints={
            "message-001": "old-message-fingerprint",
            "message-000": canonical_fingerprint(reply_target),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(
                _message("message-001", "conversation-001"),
            ),
            "message-000": canonical_message_content_fingerprint(
                reply_target,
            ),
        },
        message_reactions={
            "message-001": (old_reaction,),
            "message-000": (),
        },
        message_attachments={
            "message-001": (old_attachment,),
            "message-000": (),
        },
        message_pinned={
            "message-001": False,
            "message-000": False,
        },
        message_reply_to={
            "message-001": None,
            "message-000": None,
        },
    )

    capabilities = DestinationCapabilities(
        supports_message_editing=True,
        supports_reactions=False,
        supports_custom_emoji=True,
        supports_attachments=True,
        supports_attachment_reordering=True,
        supports_message_pinning=True,
        supports_replying=True,
        supports_message_deletion=True,
        supports_conversation_deletion=True,
        supports_identity_updates=True,
        supports_identity_deletion=True,
        supports_threads=True,
    )

    with pytest.raises(CapabilityError, match="supports_reactions"):
        list(
            Planner().plan(
                archive=archive,
                synchronization_state=state,
                capabilities=capabilities,
            ),
        )


def test_plan_rejects_unsupported_conversation_updates() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([])

    state = SynchronizationState(
        conversations={"conversation-001": Mock()},
        conversation_fingerprints={
            "conversation-001": "old-fingerprint",
        },
        conversation_parent_ids={
            "conversation-001": None,
        },
    )

    with pytest.raises(CapabilityError, match="supports_conversation_updates"):
        list(
            Planner().plan(
                archive,
                state,
                _capabilities(supports_conversation_updates=False),
            )
        )


def test_plan_rejects_unsupported_identity_creation() -> None:
    archive = _archive()
    identity = _identity("identity-001")

    archive.iter_identities.return_value = iter([identity])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.return_value = iter([])

    with pytest.raises(CapabilityError, match="supports_identity_creation"):
        list(
            Planner().plan(
                archive,
                SynchronizationState(),
                _capabilities(supports_identity_creation=False),
            )
        )


def test_plan_uses_initial_message_attachment_capability() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    attachment = _attachment()
    message = replace(
        _message("message-001", "conversation-001"),
        attachments=(attachment,),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([message])

    capabilities = _capabilities(
        supports_attachments=False,
        supports_initial_message_attachments=True,
    )

    operations = _planned_operations(
        Planner(),
        archive,
        capabilities=capabilities,
    )

    assert operations == [
        CreateConversationOperation(conversation=conversation),
        CreateMessageOperation(
            message=message,
            include_attachments=True,
        ),
    ]


def test_plan_rejects_attachments_when_neither_initial_nor_incremental_supported() -> None:
    archive = _archive()
    conversation = _conversation("conversation-001")
    message = replace(
        _message("message-001", "conversation-001"),
        attachments=(_attachment(),),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([message])

    capabilities = _capabilities(
        supports_attachments=False,
        supports_initial_message_attachments=False,
    )

    with pytest.raises(CapabilityError):
        list(
            Planner().plan(
                archive,
                SynchronizationState(),
                capabilities,
            )
        )
