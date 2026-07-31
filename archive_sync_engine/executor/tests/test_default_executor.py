"""
Tests for the default synchronization operation executor.
"""

from __future__ import annotations
from unittest.mock import Mock

import pytest

from archive_sync_engine.adapters import DestinationAdapter
from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)
from archive_sync_engine.executor import ExecutionResult
from archive_sync_engine.executor.default_executor import (
    DefaultOperationExecutor,
)
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
    SyncOperation,
    UnpinMessageOperation,
    UpdateConversationOperation,
    UpdateIdentityOperation,
)

class UnsupportedOperation(SyncOperation):
    """
    Operation used to verify unsupported-operation handling.
    """

def _destination() -> Mock:
    """
    Create a mock DestinationAdapter.
    """
    return Mock(
        spec=DestinationAdapter,
    )


def _conversation() -> CanonicalConversation:
    """
    Create a minimal canonical conversation.
    """


    return CanonicalConversation(
        id=ConversationId("conversation-001"),
        conversation_type=ConversationType.CHANNEL,
        title="General",
    )


def _identity() -> CanonicalIdentity:
    """
    Create a minimal canonical identity.
    """


    return CanonicalIdentity(
        identity_key=IdentityKey("identity-001"),
        display_name="Example User",
    )


def _message() -> CanonicalMessage:
    """
    Create a minimal canonical message.
    """


    from datetime import datetime, timezone

    return CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=ConversationId("conversation-001"),
        identity_key=IdentityKey("identity-001"),
        content="Hello world.",
        created_at=datetime(
            2026,
            7,
            31,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )


def _reaction() -> CanonicalReaction:
    """
    Create a minimal canonical reaction.
    """

    return CanonicalReaction(
        identity_key=IdentityKey("identity-001"),
        emoji="👍",
    )


def test_create_conversation_dispatches_and_returns_reference() -> None:
    destination = _destination()


    destination_ref = DestinationConversationRef(
        "destination-conversation-001",
    )

    destination.create_conversation.return_value = destination_ref

    operation = CreateConversationOperation(
        conversation=_conversation(),
    )

    result = DefaultOperationExecutor().execute(
        operation,
        destination,
    )

    destination.create_conversation.assert_called_once_with(
        operation.conversation,
    )

    assert result.conversation == destination_ref
    assert result.identity is None
    assert result.message is None
    assert result.canonical_id == "conversation-001"


def test_update_conversation_dispatches() -> None:
    destination = _destination()


    operation = UpdateConversationOperation(
        conversation=_conversation(),
    )

    result = DefaultOperationExecutor().execute(
        operation,
        destination,
    )

    destination.update_conversation.assert_called_once_with(
        operation.conversation,
    )

    assert result.conversation is None
    assert result.identity is None
    assert result.message is None
    assert result.canonical_id == "conversation-001"


def test_delete_conversation_dispatches() -> None:
    destination = _destination()


    operation = DeleteConversationOperation(
        conversation_id=ConversationId(
            "conversation-001",
        ),
    )

    result = DefaultOperationExecutor().execute(
        operation,
        destination,
    )

    destination.delete_conversation.assert_called_once_with(
        operation.conversation_id,
    )

    assert result.conversation is None
    assert result.identity is None
    assert result.message is None
    assert result.canonical_id == "conversation-001"


def test_create_identity_dispatches_and_returns_reference() -> None:
    destination = _destination()


    destination_ref = DestinationIdentityRef(
        "destination-identity-001",
    )

    destination.create_identity.return_value = destination_ref

    operation = CreateIdentityOperation(
        identity=_identity(),
    )

    result = DefaultOperationExecutor().execute(
        operation,
        destination,
    )

    destination.create_identity.assert_called_once_with(
        operation.identity,
    )

    assert result.identity == destination_ref
    assert result.conversation is None
    assert result.message is None
    assert result.canonical_id == "identity-001"


def test_update_identity_dispatches() -> None:
    destination = _destination()


    operation = UpdateIdentityOperation(
        identity=_identity(),
    )

    result = DefaultOperationExecutor().execute(
        operation,
        destination,
    )

    destination.update_identity.assert_called_once_with(
        operation.identity,
    )

    assert result.conversation is None
    assert result.identity is None
    assert result.message is None
    assert result.canonical_id == "identity-001"


def test_create_message_dispatches_and_returns_reference() -> None:
    destination = _destination()


    destination_ref = DestinationMessageRef(
        "destination-message-001",
    )

    destination.create_message.return_value = destination_ref

    operation = CreateMessageOperation(
        message=_message(),
    )

    result = DefaultOperationExecutor().execute(
        operation,
        destination,
    )

    destination.create_message.assert_called_once_with(
        operation.message,
    )

    assert result.message == destination_ref
    assert result.conversation is None
    assert result.identity is None
    assert result.canonical_id == "message-001"


def test_edit_message_dispatches() -> None:
    destination = _destination()


    operation = EditMessageOperation(
        message=_message(),
    )

    result = DefaultOperationExecutor().execute(
        operation,
        destination,
    )

    destination.edit_message.assert_called_once_with(
        operation.message,
    )

    assert result.conversation is None
    assert result.identity is None
    assert result.message is None
    assert result.canonical_id == "message-001"


def test_delete_message_dispatches() -> None:
    destination = _destination()


    operation = DeleteMessageOperation(
        message_id=MessageId("message-001"),
    )

    result = DefaultOperationExecutor().execute(
        operation,
        destination,
    )

    destination.delete_message.assert_called_once_with(
        operation.message_id,
    )

    assert result.conversation is None
    assert result.identity is None
    assert result.message is None
    assert result.canonical_id == "message-001"


def test_pin_message_dispatches() -> None:
    destination = _destination()


    operation = PinMessageOperation(
        message_id=MessageId("message-001"),
    )

    result = DefaultOperationExecutor().execute(
        operation,
        destination,
    )

    destination.pin_message.assert_called_once_with(
        operation.message_id,
    )

    assert result.conversation is None
    assert result.identity is None
    assert result.message is None


def test_unpin_message_dispatches() -> None:
    destination = _destination()


    operation = UnpinMessageOperation(
        message_id=MessageId("message-001"),
    )

    result = DefaultOperationExecutor().execute(
        operation,
        destination,
    )

    destination.unpin_message.assert_called_once_with(
        operation.message_id,
    )

    assert result.conversation is None
    assert result.identity is None
    assert result.message is None


def test_add_reaction_dispatches() -> None:
    destination = _destination()


    operation = AddReactionOperation(
        message_id=MessageId("message-001"),
        reaction=_reaction(),
    )

    result = DefaultOperationExecutor().execute(
        operation,
        destination,
    )

    destination.add_reaction.assert_called_once_with(
        operation.message_id,
        operation.reaction,
    )

    assert result.conversation is None
    assert result.identity is None
    assert result.message is None
    assert result.canonical_id == "message-001"

def test_remove_reaction_dispatches() -> None:
    destination = _destination()


    operation = RemoveReactionOperation(
        message_id=MessageId("message-001"),
        reaction=_reaction(),
    )

    result = DefaultOperationExecutor().execute(
        operation,
        destination,
    )

    destination.remove_reaction.assert_called_once_with(
        operation.message_id,
        operation.reaction,
    )

    assert result.conversation is None
    assert result.identity is None
    assert result.message is None
    assert result.canonical_id == "message-001"

def test_unsupported_operation_raises() -> None:
    destination = _destination()

    with pytest.raises(
        NotImplementedError,
        match="Unsupported operation: UnsupportedOperation",
    ):
        DefaultOperationExecutor().execute(
            UnsupportedOperation(),
            destination,
        )

def test_execution_result_defaults_to_no_references() -> None:
    result = ExecutionResult()

    assert result.canonical_id is None
    assert result.conversation is None
    assert result.identity is None
    assert result.message is None