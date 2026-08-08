"""
Tests for the synchronization planner.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from unittest.mock import Mock

import pytest

from archive_sync_engine.adapters import DestinationCapabilities
from archive_sync_engine.archive import Archive
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
from archive_sync_engine.operations import (
    CreateConversationOperation,
    CreateIdentityOperation,
    CreateMessageOperation,
)
from archive_sync_engine.planner import Planner
from archive_sync_engine.sync import SynchronizationState


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

    return DestinationCapabilities()


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


def _planned_operations(
    planner: Planner,
    archive: Archive,
    state: SynchronizationState | None = None,
) -> list:
    """
    Materialize planner output for assertions.
    """

    if state is None:
        state = SynchronizationState()

    return list(
        planner.plan(
            archive=archive,
            synchronization_state=state,
            capabilities=_capabilities(),
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