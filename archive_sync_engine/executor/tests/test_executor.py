"""
Tests for the default synchronization operation executor.
"""

from __future__ import annotations
from dataclasses import replace
from unittest.mock import Mock

import hashlib

from archive_sync_engine.asset_store import AssetStore

import pytest

from archive_sync_engine.adapters import DestinationAdapter
from archive_sync_engine.adapters.references import (
    DestinationAttachmentRef,
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)
from archive_sync_engine.executor import (
    ExecutionContext,
    ExecutionResult,
    MissingDestinationReferenceError,
)
from archive_sync_engine.executor.executor import (
    OperationExecutor,
)
from archive_sync_engine.sync.fingerprint import (
    canonical_fingerprint,
    canonical_message_content_fingerprint,
)
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


def _attachment(content: bytes = b"hello") -> CanonicalAttachment:
    """Create an attachment whose digest matches ``content``."""

    return CanonicalAttachment(
        id=AttachmentId("attachment-001"),
        filename="example.txt",
        content_type="text/plain",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
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

    result = OperationExecutor().execute(
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

    result = OperationExecutor().execute(
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

    result = OperationExecutor().execute(
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

    result = OperationExecutor().execute(
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

    result = OperationExecutor().execute(
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

    result = OperationExecutor().execute(
        operation,
        destination,
    )

    destination.create_message.assert_called_once_with(
        replace(
            operation.message,
            attachments=(),
            reactions=(),
            pinned=False,
            reply_to=None,
        ),
    )

    assert result.message == destination_ref
    assert result.conversation is None
    assert result.identity is None
    assert result.canonical_id == "message-001"


def test_create_message_does_not_mark_pending_attachment_baseline_as_synchronized() -> None:
    destination = _destination()
    attachment = _attachment()
    message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=ConversationId("conversation-001"),
        identity_key=IdentityKey("identity-001"),
        content="Hello world.",
        created_at=_message().created_at,
        attachments=(attachment,),
    )
    destination.create_message.return_value = DestinationMessageRef(
        "destination-message-001",
    )

    result = OperationExecutor().execute(
        CreateMessageOperation(message=message),
        destination,
    )

    assert result.message_attachments is None
    assert result.canonical_fingerprint is None


def test_edit_message_dispatches() -> None:
    destination = _destination()


    operation = EditMessageOperation(
        message=_message(),
    )

    result = OperationExecutor().execute(
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

    result = OperationExecutor().execute(
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


def test_add_attachment_dispatches_using_asset_store(tmp_path) -> None:
    destination = _destination()
    content = b"attachment content"
    attachment = _attachment(content)
    asset_store = AssetStore(tmp_path)
    asset_store.put_attachment(attachment, content)
    destination_ref = DestinationAttachmentRef("destination-attachment-001")
    destination.add_attachment.return_value = destination_ref

    operation = AddAttachmentOperation(
        message_id=MessageId("message-001"),
        attachment=attachment,
        resulting_attachments=(attachment,),
        canonical_fingerprint="message-fingerprint",
    )

    result = OperationExecutor(asset_store=asset_store).execute(
        operation,
        destination,
    )

    destination.add_attachment.assert_called_once_with(
        operation.message_id,
        attachment,
        content,
    )
    assert result.canonical_id == "message-001"
    assert result.canonical_fingerprint == "message-fingerprint"
    assert result.message_attachments == (attachment,)


def test_add_attachment_requires_asset_store() -> None:
    destination = _destination()
    attachment = _attachment()

    operation = AddAttachmentOperation(
        message_id=MessageId("message-001"),
        attachment=attachment,
        resulting_attachments=(attachment,),
    )

    with pytest.raises(RuntimeError, match="requires an AssetStore"):
        OperationExecutor().execute(operation, destination)

    destination.add_attachment.assert_not_called()


def test_remove_attachment_dispatches() -> None:
    destination = _destination()
    attachment = _attachment()

    operation = RemoveAttachmentOperation(
        message_id=MessageId("message-001"),
        attachment=attachment,
        resulting_attachments=(),
        canonical_fingerprint="message-fingerprint",
    )

    result = OperationExecutor().execute(operation, destination)

    destination.remove_attachment.assert_called_once_with(
        operation.message_id,
        attachment,
    )
    assert result.canonical_id == "message-001"
    assert result.canonical_fingerprint == "message-fingerprint"
    assert result.message_attachments == ()



def test_reorder_attachments_dispatches() -> None:
    destination = _destination()
    first = _attachment(b"first")
    second = CanonicalAttachment(
        id=AttachmentId("attachment-002"),
        filename="second.txt",
        content_type="text/plain",
        size=6,
        sha256=hashlib.sha256(b"second").hexdigest(),
    )

    operation = ReorderAttachmentsOperation(
        message_id=MessageId("message-001"),
        attachments=(second, first),
        canonical_fingerprint="message-fingerprint",
    )

    result = OperationExecutor().execute(operation, destination)

    destination.reorder_attachments.assert_called_once_with(
        operation.message_id,
        operation.attachments,
    )
    assert result.canonical_id == "message-001"
    assert result.canonical_fingerprint == "message-fingerprint"
    assert result.message_attachments == (second, first)


def test_pin_message_dispatches() -> None:
    destination = _destination()


    operation = PinMessageOperation(
        message_id=MessageId("message-001"),
    )

    result = OperationExecutor().execute(
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

    result = OperationExecutor().execute(
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

    result = OperationExecutor().execute(
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

    result = OperationExecutor().execute(
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

def test_pin_message_returns_component_baseline_and_optional_fingerprint() -> None:
    destination = _destination()

    operation = PinMessageOperation(
        message_id=MessageId("message-001"),
        canonical_fingerprint="message-fingerprint",
    )

    result = OperationExecutor().execute(
        operation,
        destination,
    )

    assert result.canonical_id == "message-001"
    assert result.canonical_fingerprint == "message-fingerprint"
    assert result.message_pinned is True


def test_add_reaction_returns_resulting_reaction_baseline() -> None:
    destination = _destination()
    reaction = _reaction()

    operation = AddReactionOperation(
        message_id=MessageId("message-001"),
        reaction=reaction,
        resulting_reactions=(reaction,),
        canonical_fingerprint="message-fingerprint",
    )

    result = OperationExecutor().execute(
        operation,
        destination,
    )

    assert result.canonical_id == "message-001"
    assert result.canonical_fingerprint == "message-fingerprint"
    assert result.message_reactions == (reaction,)


def test_unsupported_operation_raises() -> None:
    destination = _destination()

    with pytest.raises(
        NotImplementedError,
        match="Unsupported operation: UnsupportedOperation",
    ):
        OperationExecutor().execute(
            UnsupportedOperation(),
            destination,
        )

def test_execution_result_defaults_to_no_references() -> None:
    result = ExecutionResult()

    assert result.canonical_id is None
    assert result.conversation is None
    assert result.identity is None
    assert result.message is None

def test_execute_all_preserves_execution_context_across_operations() -> None:
    destination = _destination()

    first_message = _message()
    second_message = replace(
        first_message,
        id=MessageId("message-002"),
    )

    first_ref = DestinationMessageRef("destination-message-001")
    second_ref = DestinationMessageRef("destination-message-002")
    destination.create_message.side_effect = [
        first_ref,
        second_ref,
    ]

    operations = (
        CreateMessageOperation(message=first_message),
        CreateMessageOperation(message=second_message),
        SetMessageReplyOperation(
            message_id=second_message.id,
            reply_to=first_message.id,
        ),
    )

    context, results = OperationExecutor().execute_all(
        operations,
        destination,
    )

    destination.set_message_reply.assert_called_once_with(
        second_ref,
        first_ref,
    )
    assert context.message(first_message.id) == first_ref
    assert context.message(second_message.id) == second_ref
    assert len(results) == 3
    assert results[-1].message_reply_to == first_message.id
    assert results[-1].message_reply_to_synchronized is True


def test_set_message_reply_uses_execution_local_destination_references() -> None:
    destination = _destination()
    context = ExecutionContext()
    message_ref = DestinationMessageRef("destination-message-001")
    reply_ref = DestinationMessageRef("destination-message-002")
    context.record_message(MessageId("message-001"), message_ref)
    context.record_message(MessageId("message-002"), reply_ref)

    operation = SetMessageReplyOperation(
        message_id=MessageId("message-001"),
        reply_to=MessageId("message-002"),
        canonical_fingerprint="message-fingerprint",
    )

    result = OperationExecutor().execute(
        operation,
        destination,
        context=context,
    )

    destination.set_message_reply.assert_called_once_with(
        message_ref,
        reply_ref,
    )
    assert result.canonical_id == "message-001"
    assert result.canonical_fingerprint == "message-fingerprint"
    assert result.message_reply_to == MessageId("message-002")
    assert result.message_reply_to_synchronized is True


def test_set_message_reply_can_clear_reply() -> None:
    destination = _destination()
    context = ExecutionContext()
    message_ref = DestinationMessageRef("destination-message-001")
    context.record_message(MessageId("message-001"), message_ref)

    operation = SetMessageReplyOperation(
        message_id=MessageId("message-001"),
        reply_to=None,
        canonical_fingerprint="message-fingerprint",
    )

    result = OperationExecutor().execute(
        operation,
        destination,
        context=context,
    )

    destination.set_message_reply.assert_called_once_with(
        message_ref,
        None,
    )
    assert result.message_reply_to is None
    assert result.message_reply_to_synchronized is True


def test_set_message_reply_requires_destination_references() -> None:
    destination = _destination()
    context = ExecutionContext()

    operation = SetMessageReplyOperation(
        message_id=MessageId("message-001"),
        reply_to=MessageId("message-002"),
    )

    with pytest.raises(MissingDestinationReferenceError):
        OperationExecutor().execute(
            operation,
            destination,
            context=context,
        )

    destination.set_message_reply.assert_not_called()


def test_delete_identity_dispatches() -> None:
    destination = _destination()

    operation = DeleteIdentityOperation(
        identity_key=IdentityKey("identity-001"),
    )

    result = OperationExecutor().execute(
        operation,
        destination,
    )

    destination.delete_identity.assert_called_once_with(
        operation.identity_key,
    )

    assert result.canonical_id == "identity-001"
    assert result.deleted is True
    assert result.deleted_entity.value == "identity"


def test_create_message_strips_decomposed_components_from_destination_creation() -> None:
    destination = _destination()
    attachment = _attachment()
    reaction = _reaction()
    message = replace(
        _message(),
        attachments=(attachment,),
        reactions=(reaction,),
        pinned=True,
        reply_to=MessageId("message-002"),
    )
    destination.create_message.return_value = DestinationMessageRef(
        "destination-message-001",
    )

    result = OperationExecutor().execute(
        CreateMessageOperation(message=message),
        destination,
    )

    destination.create_message.assert_called_once_with(
        replace(
            message,
            attachments=(),
            reactions=(),
            pinned=False,
            reply_to=None,
        ),
    )
    assert result.canonical_fingerprint is None
    assert result.message_content_fingerprint == (
        canonical_message_content_fingerprint(message)
    )
    assert result.message_attachments is None
    assert result.message_reactions is None
    assert result.message_pinned is None
    assert not result.message_reply_to_synchronized
