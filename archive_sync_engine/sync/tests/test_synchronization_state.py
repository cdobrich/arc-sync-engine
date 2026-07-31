"""
Tests for SynchronizationState.
"""

from __future__ import annotations
from dataclasses import FrozenInstanceError

import pytest

from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)
from archive_sync_engine.sync.synchronization_state import (
    SynchronizationState,
)

from archive_sync_engine.executor.result import ExecutionResult


def test_with_conversation_returns_new_state() -> None:
    state = SynchronizationState()

    destination_ref = DestinationConversationRef(
        "destination-conversation-001",
    )

    updated = state.with_conversation(
        "conversation-001",
        destination_ref,
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
    )

    assert updated is not state
    assert state.messages == {}

    assert updated.messages == {
        "message-001": destination_ref,
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
    )

    updated = state.apply_execution_result(
        "message-001",
        result,
    )

    assert updated.messages == {
        "message-001": destination_ref,
    }

    assert state.messages == {}

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

