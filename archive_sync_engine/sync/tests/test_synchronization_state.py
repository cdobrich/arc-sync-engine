"""
Tests for SynchronizationState.
"""

from __future__ import annotations
from dataclasses import FrozenInstanceError
from unittest.mock import Mock

import pytest

from archive_sync_engine.models import CanonicalAttachment
from archive_sync_engine.models.ids import AttachmentId, MessageId

from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)
from archive_sync_engine.sync.synchronization_state import (
    SynchronizationState,
)
from archive_sync_engine.sync.fingerprint import canonical_fingerprint

from archive_sync_engine.executor.result import (
    DeletedEntityType,
    ExecutionResult,
)


def test_with_conversation_returns_new_state() -> None:
    state = SynchronizationState()

    destination_ref = DestinationConversationRef(
        "destination-conversation-001",
    )

    updated = state.with_conversation(
        "conversation-001",
        destination_ref,
        "fingerprint-001",
        None,
    )

    assert updated is not state
    assert state.conversations == {}

    assert updated.conversations == {
        "conversation-001": destination_ref,
    }


def test_with_identity_returns_new_state() -> None:
    state = SynchronizationState()

    destination_ref = DestinationIdentityRef(
        "destination-identity-001",
    )

    updated = state.with_identity(
        "identity-001",
        destination_ref,
        "fingerprint-001",
    )

    assert updated is not state
    assert state.identities == {}

    assert updated.identities == {
        "identity-001": destination_ref,
    }


def test_with_message_returns_new_state() -> None:
    state = SynchronizationState()

    destination_ref = DestinationMessageRef(
        "destination-message-001",
    )

    updated = state.with_message(
        "message-001",
        destination_ref,
        "fingerprint-001",
        "content-fingerprint-001",
        (),
        (),
        False,
    )

    assert updated is not state
    assert state.messages == {}

    assert updated.messages == {
        "message-001": destination_ref,
    }
    assert updated.message_attachments == {
        "message-001": (),
    }
    assert updated.message_reply_to == {
        "message-001": None,
    }


def test_with_message_records_reply_baseline() -> None:
    state = SynchronizationState()

    updated = state.with_message(
        "message-001",
        DestinationMessageRef("destination-message-001"),
        "fingerprint-001",
        "content-fingerprint-001",
        (),
        (),
        False,
        MessageId("message-parent"),
    )

    assert updated.message_reply_to == {
        "message-001": MessageId("message-parent"),
    }


def test_without_message_removes_reply_baseline() -> None:
    state = SynchronizationState(
        messages={
            "message-001": DestinationMessageRef("destination-message-001"),
        },
        message_fingerprints={"message-001": "fingerprint-001"},
        message_content_fingerprints={"message-001": "content-fingerprint-001"},
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": MessageId("message-parent")},
    )

    updated = state.without_message("message-001")

    assert updated.message_reply_to == {}
    assert state.message_reply_to == {
        "message-001": MessageId("message-parent"),
    }


def test_with_methods_preserve_existing_state() -> None:
    conversation_ref = DestinationConversationRef(
        "destination-conversation-001",
    )

    identity_ref = DestinationIdentityRef(
        "destination-identity-001",
    )

    message_ref = DestinationMessageRef(
        "destination-message-001",
    )

    state = SynchronizationState(
        conversations={
            "conversation-001": conversation_ref,
        },
        identities={
            "identity-001": identity_ref,
        },
        messages={
            "message-001": message_ref,
        },
    )

    updated = state.with_message(
        "message-002",
        DestinationMessageRef(
            "destination-message-002",
        ),
        "fingerprint-002",
        "content-fingerprint-002",
        (),
        (),
        False,
    )

    assert updated.conversations == state.conversations
    assert updated.identities == state.identities

    assert updated.messages == {
        "message-001": message_ref,
        "message-002": DestinationMessageRef(
            "destination-message-002",
        ),
    }

def test_synchronization_state_is_frozen() -> None:
    state = SynchronizationState()

    with pytest.raises(FrozenInstanceError):
        setattr(
            state,
            "conversations",
            {},
        )

def test_apply_execution_result_adds_conversation_reference() -> None:
    state = SynchronizationState()

    destination_ref = DestinationConversationRef(
        "destination-conversation-001",
    )

    result = ExecutionResult(
        conversation=destination_ref,
        canonical_fingerprint="fingerprint-001",
        conversation_parent_id=None,
    )

    updated = state.apply_execution_result(
        "conversation-001",
        result,
    )

    assert updated.conversations == {
        "conversation-001": destination_ref,
    }

    assert state.conversations == {}

def test_apply_execution_result_adds_identity_reference() -> None:
    state = SynchronizationState()

    destination_ref = DestinationIdentityRef(
        "destination-identity-001",
    )

    result = ExecutionResult(
        identity=destination_ref,
        canonical_fingerprint="fingerprint-001",
    )

    updated = state.apply_execution_result(
        "identity-001",
        result,
    )

    assert updated.identities == {
        "identity-001": destination_ref,
    }

    assert state.identities == {}

def test_apply_execution_result_adds_message_reference() -> None:
    state = SynchronizationState()

    destination_ref = DestinationMessageRef(
        "destination-message-001",
    )

    result = ExecutionResult(
        message=destination_ref,
        canonical_fingerprint="fingerprint-001",
        message_content_fingerprint="content-fingerprint-001",
        message_reactions=(),
        message_attachments=(),
        message_pinned=False,
        message_reply_to=None,
        message_reply_to_synchronized=True,
    )

    updated = state.apply_execution_result(
        "message-001",
        result,
    )

    assert updated.messages == {
        "message-001": destination_ref,
    }

    assert state.messages == {}

def test_apply_execution_result_updates_message_components_without_completing_fingerprint() -> None:
    state = SynchronizationState(
        messages={
            "message-001": DestinationMessageRef("destination-message-001"),
        },
        message_fingerprints={
            "message-001": "old-fingerprint",
        },
        message_content_fingerprints={
            "message-001": "old-content-fingerprint",
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

    updated = state.apply_execution_result(
        "message-001",
        ExecutionResult(
            canonical_id="message-001",
            message_content_fingerprint="new-content-fingerprint",
        ),
    )

    assert updated.message_content_fingerprints == {
        "message-001": "new-content-fingerprint",
    }
    assert updated.message_fingerprints == {
        "message-001": "old-fingerprint",
    }


def test_apply_execution_result_updates_attachment_baseline_without_completing_fingerprint() -> None:
    state = SynchronizationState(
        messages={
            "message-001": DestinationMessageRef("destination-message-001"),
        },
        message_fingerprints={"message-001": "old-fingerprint"},
        message_content_fingerprints={"message-001": "old-content-fingerprint"},
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    attachment = CanonicalAttachment(
        id=AttachmentId("attachment-001"),
        filename="example.txt",
        content_type="text/plain",
        size=1,
        sha256="a" * 64,
    )

    updated = state.apply_execution_result(
        "message-001",
        ExecutionResult(
            canonical_id="message-001",
            message_attachments=(attachment,),
        ),
    )

    assert updated.message_attachments == {"message-001": (attachment,)}
    assert updated.message_fingerprints == {"message-001": "old-fingerprint"}


def test_apply_execution_result_preserves_uncompleted_reply_baseline() -> None:
    state = SynchronizationState(
        messages={
            "message-001": DestinationMessageRef("destination-message-001"),
        },
        message_fingerprints={"message-001": "old-fingerprint"},
        message_content_fingerprints={"message-001": "old-content-fingerprint"},
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
    )

    updated = state.apply_execution_result(
        "message-001",
        ExecutionResult(
            canonical_id="message-001",
            message_reply_to=None,
            message_reply_to_synchronized=False,
        ),
    )

    assert updated.message_reply_to == {}
    assert updated.message_fingerprints == {
        "message-001": "old-fingerprint",
    }


def test_apply_execution_result_completes_message_fingerprint() -> None:
    state = SynchronizationState(
        messages={
            "message-001": DestinationMessageRef("destination-message-001"),
        },
        message_fingerprints={
            "message-001": "old-fingerprint",
        },
        message_content_fingerprints={
            "message-001": "new-content-fingerprint",
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

    updated = state.apply_execution_result(
        "message-001",
        ExecutionResult(
            canonical_id="message-001",
            canonical_fingerprint="new-fingerprint",
            message_pinned=True,
            message_reply_to=None,
            message_reply_to_synchronized=True,
        ),
    )

    assert updated.message_fingerprints == {
        "message-001": "new-fingerprint",
    }
    assert updated.message_pinned == {
        "message-001": True,
    }


def test_apply_execution_result_without_reference_returns_same_state() -> None:
    state = SynchronizationState()

    result = ExecutionResult()

    updated = state.apply_execution_result(
        "message-001",
        result,
    )

    assert updated is state

def test_apply_execution_result_rejects_multiple_references() -> None:
    state = SynchronizationState()

    result = ExecutionResult(
        conversation=DestinationConversationRef(
            "destination-conversation-001",
        ),
        message=DestinationMessageRef(
            "destination-message-001",
        ),
    )

    with pytest.raises(
        ValueError,
        match="multiple destination references",
    ):
        state.apply_execution_result(
            "canonical-001",
            result,
        )



def test_apply_execution_result_deletes_message() -> None:
    state = SynchronizationState(
        messages={
            "message-001": DestinationMessageRef("destination-message-001"),
        },
        message_fingerprints={
            "message-001": "fingerprint-001",
        },
    )

    updated = state.apply_execution_result(
        "message-001",
        ExecutionResult(
            canonical_id="message-001",
            deleted=True,
            deleted_entity=DeletedEntityType.MESSAGE,
        ),
    )

    assert updated.messages == {}
    assert updated.message_fingerprints == {}
    assert updated.message_attachments == {}
    assert state.messages["message-001"].id == "destination-message-001"


def test_apply_execution_result_deletes_conversation_and_parent_metadata() -> None:
    state = SynchronizationState(
        conversations={
            "conversation-001": DestinationConversationRef("destination-conversation-001"),
        },
        conversation_fingerprints={
            "conversation-001": "fingerprint-001",
        },
        conversation_parent_ids={
            "conversation-001": None,
        },
    )

    updated = state.apply_execution_result(
        "conversation-001",
        ExecutionResult(
            canonical_id="conversation-001",
            deleted=True,
            deleted_entity=DeletedEntityType.CONVERSATION,
        ),
    )

    assert updated.conversations == {}
    assert updated.conversation_fingerprints == {}
    assert updated.conversation_parent_ids == {}


def test_apply_execution_result_rejects_untyped_deletion() -> None:
    with pytest.raises(
        ValueError,
        match="must identify its entity type",
    ):
        SynchronizationState().apply_execution_result(
            "message-001",
            ExecutionResult(
                canonical_id="message-001",
                deleted=True,
            ),
        )


def test_partial_message_execution_requires_existing_message() -> None:
    state = SynchronizationState()

    with pytest.raises(ValueError, match="existing synchronized message"):
        state.apply_execution_result(
            canonical_id="message-001",
            result=ExecutionResult(
                canonical_id="message-001",
                message_pinned=True,
            ),
        )


def test_message_fingerprint_cannot_advance_without_component_update() -> None:
    state = SynchronizationState(
        messages={"message-001": Mock()},
        message_fingerprints={"message-001": "old"},
        message_content_fingerprints={"message-001": "content"},
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    with pytest.raises(ValueError, match="without a message reference"):
        state.apply_execution_result(
            canonical_id="message-001",
            result=ExecutionResult(
                canonical_id="message-001",
                canonical_fingerprint="new",
            ),
        )


def test_complete_message_fingerprint_requires_existing_component_baselines() -> None:
    state = SynchronizationState(
        messages={"message-001": Mock()},
        message_fingerprints={"message-001": "old"},
        message_content_fingerprints={"message-001": "content"},
        message_reactions={"message-001": ()},
        message_attachments={"message-001": ()},
        message_reply_to={"message-001": None},
    )

    with pytest.raises(ValueError, match="pin"):
        state.apply_execution_result(
            canonical_id="message-001",
            result=ExecutionResult(
                canonical_id="message-001",
                canonical_fingerprint="new",
                message_content_fingerprint="content",
                message_reactions=(),
                message_attachments=(),
            ),
        )


def test_apply_execution_result_deletes_identity() -> None:
    state = SynchronizationState(
        identities={
            "identity-001": DestinationIdentityRef(
                "destination-identity-001",
            ),
        },
        identity_fingerprints={
            "identity-001": "fingerprint-001",
        },
    )

    updated = state.apply_execution_result(
        "identity-001",
        ExecutionResult(
            canonical_id="identity-001",
            deleted=True,
            deleted_entity=DeletedEntityType.IDENTITY,
        ),
    )

    assert updated.identities == {}
    assert updated.identity_fingerprints == {}
    assert state.identities["identity-001"].id == "destination-identity-001"


def test_without_message_rejects_dangling_reply_baseline() -> None:
    state = SynchronizationState(
        messages={
            "message-parent": DestinationMessageRef("destination-parent"),
            "message-reply": DestinationMessageRef("destination-reply"),
        },
        message_reply_to={
            "message-reply": MessageId("message-parent"),
        },
    )

    with pytest.raises(
        ValueError,
        match="still reference it as a reply target",
    ):
        state.without_message("message-parent")

    assert state.messages == {
        "message-parent": DestinationMessageRef("destination-parent"),
        "message-reply": DestinationMessageRef("destination-reply"),
    }
    assert state.message_reply_to == {
        "message-reply": MessageId("message-parent"),
    }


def test_without_message_preserves_unrelated_reply_baselines() -> None:
    state = SynchronizationState(
        messages={
            "message-parent": DestinationMessageRef("destination-parent"),
            "message-reply": DestinationMessageRef("destination-reply"),
            "message-other": DestinationMessageRef("destination-other"),
        },
        message_reply_to={
            "message-reply": MessageId("message-parent"),
            "message-other": None,
        },
    )

    with pytest.raises(ValueError):
        state.without_message("message-parent")

    updated = state.without_message("message-other")

    assert updated.message_reply_to == {
        "message-reply": MessageId("message-parent"),
    }
    assert state.message_reply_to == {
        "message-reply": MessageId("message-parent"),
        "message-other": None,
    }
