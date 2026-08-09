"""
Tests for the synchronization planner.
"""

from __future__ import annotations

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
from archive_sync_engine.operations import (
    AddReactionOperation,
    CreateConversationOperation,
    CreateIdentityOperation,
    CreateMessageOperation,
    DeleteConversationOperation,
    DeleteMessageOperation,
    EditMessageOperation,
    PinMessageOperation,
    RemoveReactionOperation,
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


def _capabilities() -> DestinationCapabilities:
    """
    Create destination capabilities for planner tests.
    """

    return DestinationCapabilities(
        supports_threads=True,
        supports_message_editing=True,
        supports_message_deletion=True,
        supports_conversation_deletion=True,
        supports_message_pinning=True,
        supports_reactions=True,
        supports_custom_emoji=True,
        supports_attachments=True,
        supports_replying=True,
        supports_identity_updates=True,
    )


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


def _reaction(
    identity_key: str = "identity-002",
    emoji: str = "👍",
) -> CanonicalReaction:
    """
    Create a canonical reaction for planner tests.
    """

    return CanonicalReaction(
        identity_key=IdentityKey(identity_key),
        emoji=emoji,
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
        message_pinned={
            "message-001": False,
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
        message_pinned={"message-001": False},
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
        message_pinned={"message-001": False},
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
        message_pinned={"message-001": False},
    )

    operations = _planned_operations(Planner(), archive, state)

    assert operations == [
        EditMessageOperation(
            message=desired_message,
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
        message_pinned={"message-001": False},
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
        message_pinned={"message-001": False},
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
        message_pinned={"message-001": False},
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
        message_pinned={"message-001": False},
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
        message_pinned={"message-001": False},
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
