"""
Tests for the synchronization coordinator.
"""

from __future__ import annotations
from unittest.mock import Mock, call

import pytest

from archive_sync_engine.adapters import (
    DestinationAdapter,
    DestinationCapabilities,
)
from archive_sync_engine.archive import Archive
from archive_sync_engine.operations import (
    SyncOperation,
)
from archive_sync_engine.planner import Planner
from archive_sync_engine.repository import StateRepository, InMemoryStateRepository
from archive_sync_engine.sync.coordinator import SyncCoordinator
from archive_sync_engine.sync.synchronization_state import (
    SynchronizationState,
)

from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
)
from archive_sync_engine.executor import (
    ExecutionResult,
    OperationExecutor,
)
from archive_sync_engine.models import (
    CanonicalConversation,
)
from archive_sync_engine.models.enums import (
    ConversationType,
)
from archive_sync_engine.models.ids import (
    ConversationId,
)
from archive_sync_engine.operations import (
    CreateConversationOperation,
)


def _archive() -> Archive:
    """
    Create a mock Archive.
    """

    return Mock(
        spec=Archive,
    )


def _planner() -> Mock:
    """
    Create a mock Planner.
    """

    return Mock(
        spec=Planner,
    )


def _executor() -> Mock:
    """
    Create a mock OperationExecutor.
    """

    return Mock(
        spec=OperationExecutor,
    )


def _destination() -> Mock:
    """
    Create a mock DestinationAdapter.
    """

    return Mock(
        spec=DestinationAdapter,
    )


def _capabilities() -> DestinationCapabilities:
    """
    Create destination capabilities for coordinator tests.
    """

    return DestinationCapabilities(
        supports_message_editing=True,
        supports_message_deletion=True,
        supports_message_pinning=True,
        supports_reactions=True,
        supports_custom_emoji=True,
        supports_attachments=True,
        supports_replying=True,
        supports_identity_updates=True,
    )


def _state_repository() -> Mock:
    """
    Create a mock StateRepository.
    """

    return Mock(
        spec=StateRepository,
    )


def test_synchronize_loads_state_and_plans_operations() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()

    state = SynchronizationState()

    state_repository.load_synchronization_state.return_value = state
    planner.plan.return_value = iter(())

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    coordinator.synchronize()

    state_repository.load_synchronization_state.assert_called_once_with()

    planner.plan.assert_called_once_with(
        archive=archive,
        synchronization_state=state,
        capabilities=capabilities,
    )

    executor.execute.assert_not_called()


def test_synchronize_executes_operations_in_planner_order() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()

    executor.execute.return_value = ExecutionResult()

    state = SynchronizationState()

    operation_one = Mock(
        spec=SyncOperation,
    )

    operation_two = Mock(
        spec=SyncOperation,
    )

    operation_three = Mock(
        spec=SyncOperation,
    )

    state_repository.load_synchronization_state.return_value = state

    planner.plan.return_value = iter(
        (
            operation_one,
            operation_two,
            operation_three,
        ),
    )

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    coordinator.synchronize()

    assert executor.execute.call_args_list == [
        call(
            operation=operation_one,
            destination=destination,
        ),
        call(
            operation=operation_two,
            destination=destination,
        ),
        call(
            operation=operation_three,
            destination=destination,
        ),
    ]


def test_synchronize_passes_destination_to_every_operation() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()

    executor.execute.return_value = ExecutionResult()

    state_repository.load_synchronization_state.return_value = (
        SynchronizationState()
    )

    operations: tuple[SyncOperation, ...] = (
        Mock(
            spec=SyncOperation,
        ),
        Mock(
            spec=SyncOperation,
        ),
    )

    planner.plan.return_value = iter(operations)

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    coordinator.synchronize()

    assert executor.execute.call_count == 2

    for call in executor.execute.call_args_list:
        assert call.kwargs["destination"] is destination


def test_synchronize_does_not_execute_when_planner_returns_no_operations() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()

    state_repository.load_synchronization_state.return_value = (
        SynchronizationState()
    )

    planner.plan.return_value = iter(())

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    coordinator.synchronize()

    executor.execute.assert_not_called()


def test_synchronize_propagates_executor_failure() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()

    state_repository.load_synchronization_state.return_value = (
        SynchronizationState()
    )

    operation = Mock(
        spec=SyncOperation,
    )

    planner.plan.return_value = iter((operation,))

    executor.execute.side_effect = RuntimeError(
        "destination operation failed",
    )

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    try:
        coordinator.synchronize()
    except RuntimeError as exc:
        assert str(exc) == "destination operation failed"
    else:
        raise AssertionError(
            "Expected executor failure to propagate."
        )

    executor.execute.assert_called_once_with(
        operation=operation,
        destination=destination,
    )

def test_synchronize_records_successful_execution() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()

    initial_state = SynchronizationState()

    operation = Mock(
        spec=SyncOperation,
    )

    result = ExecutionResult()

    state_repository.load_synchronization_state.return_value = (
        initial_state
    )

    planner.plan.return_value = iter(
        (
            operation,
        ),
    )

    executor.execute.return_value = result

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    coordinator.synchronize()

    executor.execute.assert_called_once_with(
        operation=operation,
        destination=destination,
    )

    state_repository.record_execution.assert_called_once_with(
        operation=operation,
        result=result,
        synchronization_state=initial_state,
    )

def test_synchronize_does_not_record_failed_execution() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()

    state_repository.load_synchronization_state.return_value = (
        SynchronizationState()
    )

    operation = Mock(
        spec=SyncOperation,
    )

    planner.plan.return_value = iter(
        (
            operation,
        ),
    )

    executor.execute.side_effect = RuntimeError(
        "destination operation failed",
    )

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    with pytest.raises(
            RuntimeError,
            match="destination operation failed",
    ):
        coordinator.synchronize()

    executor.execute.assert_called_once_with(
        operation=operation,
        destination=destination,
    )

    state_repository.record_execution.assert_not_called()

def test_synchronize_accumulates_execution_state() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()

    initial_state = SynchronizationState()

    conversation = CanonicalConversation(
        id=ConversationId("conversation-001"),
        conversation_type=ConversationType.CHANNEL,
        title="General",
    )

    operation = CreateConversationOperation(
        conversation=conversation,
    )

    destination_ref = DestinationConversationRef(
        "destination-conversation-001",
    )

    result = ExecutionResult(
        conversation=destination_ref,
        canonical_id=str(conversation.id),
    )

    state_repository.load_synchronization_state.return_value = (
        initial_state
    )

    planner.plan.return_value = iter(
        (
            operation,
        ),
    )

    executor.execute.return_value = result

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    coordinator.synchronize()

    expected_state = initial_state.with_conversation(
        canonical_id=str(conversation.id),
        destination_ref=destination_ref,
    )

    state_repository.record_execution.assert_called_once_with(
        operation=operation,
        result=result,
        synchronization_state=expected_state,
    )

def test_synchronize_accumulates_multiple_execution_results() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()

    initial_state = SynchronizationState()

    conversation_one = CanonicalConversation(
        id=ConversationId("conversation-001"),
        conversation_type=ConversationType.CHANNEL,
        title="General",
    )

    conversation_two = CanonicalConversation(
        id=ConversationId("conversation-002"),
        conversation_type=ConversationType.CHANNEL,
        title="Random",
    )

    operation_one = CreateConversationOperation(
        conversation=conversation_one,
    )

    operation_two = CreateConversationOperation(
        conversation=conversation_two,
    )

    destination_ref_one = DestinationConversationRef(
        "destination-conversation-001",
    )

    destination_ref_two = DestinationConversationRef(
        "destination-conversation-002",
    )

    result_one = ExecutionResult(
        conversation=destination_ref_one,
        canonical_id=str(conversation_one.id),
    )

    result_two = ExecutionResult(
        conversation=destination_ref_two,
        canonical_id=str(conversation_two.id),
    )

    state_repository.load_synchronization_state.return_value = (
        initial_state
    )

    planner.plan.return_value = iter(
        (
            operation_one,
            operation_two,
        ),
    )

    executor.execute.side_effect = (
        result_one,
        result_two,
    )

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    coordinator.synchronize()

    expected_state_one = initial_state.with_conversation(
        canonical_id=str(conversation_one.id),
        destination_ref=destination_ref_one,
    )

    expected_state_two = expected_state_one.with_conversation(
        canonical_id=str(conversation_two.id),
        destination_ref=destination_ref_two,
    )

    assert state_repository.record_execution.call_args_list == [
        call(
            operation=operation_one,
            result=result_one,
            synchronization_state=expected_state_one,
        ),
        call(
            operation=operation_two,
            result=result_two,
            synchronization_state=expected_state_two,
        ),
    ]

def test_synchronize_records_unchanged_state_when_execution_produces_no_reference() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()

    initial_state = SynchronizationState()

    operation = Mock(
        spec=SyncOperation,
    )

    result = ExecutionResult(
        canonical_id="message-001",
    )

    state_repository.load_synchronization_state.return_value = (
        initial_state
    )

    planner.plan.return_value = iter(
        (
            operation,
        ),
    )

    executor.execute.return_value = result

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    coordinator.synchronize()

    state_repository.record_execution.assert_called_once_with(
        operation=operation,
        result=result,
        synchronization_state=initial_state,
    )

def test_synchronize_records_updated_state_after_execution() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()

    initial_state = SynchronizationState()

    operation = Mock(
        spec=SyncOperation,
    )

    destination_ref = DestinationConversationRef(
        "destination-conversation-001",
    )

    result = ExecutionResult(
        canonical_id="conversation-001",
        conversation=destination_ref,
    )

    state_repository.load_synchronization_state.return_value = (
        initial_state
    )

    planner.plan.return_value = iter(
        (
            operation,
        ),
    )

    executor.execute.return_value = result

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    coordinator.synchronize()

    state_repository.record_execution.assert_called_once()

    recorded_call = (
        state_repository.record_execution.call_args
    )

    assert recorded_call.kwargs["operation"] is operation
    assert recorded_call.kwargs["result"] is result

    recorded_state = (
        recorded_call.kwargs["synchronization_state"]
    )

    assert recorded_state is not initial_state

    assert (
        recorded_state.conversations["conversation-001"]
        == destination_ref
    )

    assert recorded_state.identities == {}
    assert recorded_state.messages == {}

def test_synchronize_persists_state_in_concrete_repository() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()

    state_repository = InMemoryStateRepository()

    operation = CreateConversationOperation(
        conversation=CanonicalConversation(
            id=ConversationId("conversation-001"),
            conversation_type=ConversationType.CHANNEL,
            title="General",
        ),
    )

    destination_ref = DestinationConversationRef(
        "destination-conversation-001",
    )

    result = ExecutionResult(
        canonical_id=str(operation.conversation.id),
        conversation=destination_ref,
    )

    planner.plan.return_value = iter(
        (
            operation,
        ),
    )

    executor.execute.return_value = result

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    coordinator.synchronize()

    state = state_repository.load_synchronization_state()

    assert (
        state.conversations["conversation-001"]
        == destination_ref
    )