"""
Tests for the synchronization coordinator.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from dataclasses import replace
from unittest.mock import ANY, Mock, call

import pytest

from archive_sync_engine.adapters import (
    AuthorizationError,
    DestinationAdapter,
    DestinationCapabilities,
)
from archive_sync_engine.archive import Archive
from archive_sync_engine.asset_store import AssetStore
from archive_sync_engine.operations import (
    SyncOperation,
)
from archive_sync_engine.planner import Planner
from archive_sync_engine.repository import (
    InMemoryStateRepository,
    SQLiteStateRepository,
    StateRepository,
)
from archive_sync_engine.sync.coordinator import SyncCoordinator
from archive_sync_engine.sync.fingerprint import (
    canonical_fingerprint,
    canonical_message_content_fingerprint,
)
from archive_sync_engine.sync.synchronization_state import (
    SynchronizationState,
)

from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
    DestinationMessageRef,
)
from archive_sync_engine.executor import (
    ExecutionResult,
    OperationExecutor,
)
from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalMessage,
    CanonicalReaction,
)
from archive_sync_engine.models.enums import (
    ConversationType,
)
from archive_sync_engine.models.ids import (
    AttachmentId,
    ConversationId,
    IdentityKey,
    MessageId,
)
from archive_sync_engine.operations import (
    CreateConversationOperation,
    CreateMessageOperation,
    EditMessageOperation,
    PinMessageOperation,
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

    destination = Mock(
        spec=DestinationAdapter,
    )
    destination.reconcile_synchronization_state.side_effect = lambda state: state
    return destination


def _capabilities() -> DestinationCapabilities:
    """
    Create destination capabilities for coordinator tests.
    """

    return DestinationCapabilities(
        supports_message_editing=True,
        supports_message_deletion=True,
        supports_conversation_deletion=True,
        supports_message_pinning=True,
        supports_reactions=True,
        supports_custom_emoji=True,
        supports_attachments=True,
        supports_attachment_reordering=True,
        supports_replying=True,
        supports_identity_updates=True,
        supports_identity_deletion=True,
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


def test_synchronize_validates_complete_plan_before_execution() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()
    state_repository.load_synchronization_state.return_value = SynchronizationState()

    operation_one = Mock(spec=SyncOperation)
    operation_two = Mock(spec=SyncOperation)
    planner.plan.return_value = iter((operation_one, operation_two))
    destination.validate_operations.side_effect = RuntimeError("invalid destination plan")

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    with pytest.raises(RuntimeError, match="invalid destination plan"):
        coordinator.synchronize()

    destination.validate_operations.assert_called_once_with(
        (operation_one, operation_two),
    )
    executor.execute.assert_not_called()
    state_repository.record_execution.assert_not_called()



def test_synchronize_persists_destination_reconciliation_without_fake_execution(
    tmp_path,
) -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    class ReconciliationDestination:
        def __init__(self, repaired_state):
            self.repaired_state = repaired_state

        def reconcile_synchronization_state(self, state):
            self.received_state = state
            return self.repaired_state

        def validate_operations(self, operations):
            del operations

        def prepare_archive(self, archive, asset_store):
            del archive, asset_store

    capabilities = _capabilities()

    initial_state = SynchronizationState(
        conversations={
            "conversation-1": DestinationConversationRef("deleted-channel"),
        },
        conversation_fingerprints={"conversation-1": "fingerprint"},
        conversation_parent_ids={"conversation-1": None},
    )
    repaired_state = SynchronizationState()
    destination = ReconciliationDestination(repaired_state)
    planner.plan.return_value = iter(())

    path = tmp_path / "state.sqlite3"
    with SQLiteStateRepository(path) as repository:
        repository.record_execution(
            operation=Mock(spec=SyncOperation),
            result=ExecutionResult(canonical_id="conversation-1"),
            synchronization_state=initial_state,
        )

    with SQLiteStateRepository(path) as repository:
        coordinator = SyncCoordinator(
            archive=archive,
            planner=planner,
            executor=executor,
            destination=destination,
            capabilities=capabilities,
            state_repository=repository,
        )

        assert coordinator.synchronize() == ()
        assert repository.load_synchronization_state() == repaired_state
        assert len(repository.query_execution_log()) == 1

    assert destination.received_state == initial_state
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
            context=ANY,
        ),
        call(
            operation=operation_two,
            destination=destination,
            context=ANY,
        ),
        call(
            operation=operation_three,
            destination=destination,
            context=ANY,
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
        context=ANY,
    )

def test_synchronize_persists_component_progress_before_later_failure() -> None:
    archive = _archive()
    destination = _destination()
    state_repository = InMemoryStateRepository()

    old_reaction = CanonicalReaction(
        emoji="👍",
        identity_key=IdentityKey("identity-001"),
    )
    new_reaction = CanonicalReaction(
        emoji="❤️",
        identity_key=IdentityKey("identity-001"),
    )

    old_message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=ConversationId("conversation-001"),
        identity_key=IdentityKey("identity-001"),
        content="old content",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
        pinned=False,
        reactions=(old_reaction,),
    )
    desired_message = CanonicalMessage(
        id=old_message.id,
        conversation_id=old_message.conversation_id,
        identity_key=old_message.identity_key,
        content="new content",
        created_at=old_message.created_at,
        pinned=True,
        reactions=(new_reaction,),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.side_effect = lambda: iter([desired_message])

    initial_state = SynchronizationState(
        messages={
            "message-001": DestinationMessageRef("destination-message-001"),
        },
        message_fingerprints={
            "message-001": canonical_fingerprint(old_message),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(old_message),
        },
        message_reactions={"message-001": (old_reaction,)},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )
    state_repository = InMemoryStateRepository(
        synchronization_state=initial_state,
    )

    destination.pin_message.side_effect = RuntimeError(
        "pin failed",
    )

    coordinator = SyncCoordinator(
        archive=archive,
        planner=Planner(),
        executor=OperationExecutor(),
        destination=destination,
        capabilities=_capabilities(),
        state_repository=state_repository,
    )

    with pytest.raises(RuntimeError, match="pin failed"):
        coordinator.synchronize()

    state = state_repository.load_synchronization_state()

    assert state.message_content_fingerprints["message-001"] == (
        canonical_message_content_fingerprint(desired_message)
    )
    assert state.message_reactions["message-001"] == (new_reaction,)
    assert state.message_pinned["message-001"] is False
    assert state.message_fingerprints["message-001"] == (
        canonical_fingerprint(old_message)
    )

    remaining_operations = list(
        Planner().plan(
            archive=archive,
            synchronization_state=state,
            capabilities=_capabilities(),
        ),
    )

    assert remaining_operations == [
        PinMessageOperation(
            message_id=desired_message.id,
            canonical_fingerprint=canonical_fingerprint(desired_message),
        ),
    ]


def test_synchronize_persists_attachment_progress_before_later_pin_failure(
    tmp_path,
) -> None:
    archive = _archive()
    destination = _destination()
    content = b"attachment content"
    attachment = CanonicalAttachment(
        id=AttachmentId("attachment-001"),
        filename="example.txt",
        content_type="text/plain",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )

    old_message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=ConversationId("conversation-001"),
        identity_key=IdentityKey("identity-001"),
        content="old content",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
        pinned=False,
    )
    desired_message = CanonicalMessage(
        id=old_message.id,
        conversation_id=old_message.conversation_id,
        identity_key=old_message.identity_key,
        content="new content",
        created_at=old_message.created_at,
        pinned=True,
        attachments=(attachment,),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.side_effect = lambda: iter([desired_message])

    state_repository = InMemoryStateRepository(
        synchronization_state=SynchronizationState(
            messages={"message-001": Mock()},
            message_fingerprints={
                "message-001": canonical_fingerprint(old_message),
            },
            message_content_fingerprints={
                "message-001": canonical_message_content_fingerprint(old_message),
            },
            message_reactions={"message-001": ()},
            message_attachments={"message-001": ()},
            message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
        ),
    )

    asset_store = AssetStore(tmp_path)
    asset_store.put_attachment(attachment, content)

    destination.pin_message.side_effect = RuntimeError("pin failed")

    coordinator = SyncCoordinator(
        archive=archive,
        planner=Planner(),
        executor=OperationExecutor(asset_store=asset_store),
        destination=destination,
        capabilities=_capabilities(),
        state_repository=state_repository,
    )

    with pytest.raises(RuntimeError, match="pin failed"):
        coordinator.synchronize()

    state = state_repository.load_synchronization_state()

    assert state.message_content_fingerprints["message-001"] == (
        canonical_message_content_fingerprint(desired_message)
    )
    assert state.message_attachments["message-001"] == (attachment,)
    assert state.message_pinned["message-001"] is False
    assert state.message_fingerprints["message-001"] == (
        canonical_fingerprint(old_message)
    )

    remaining_operations = list(
        Planner().plan(
            archive=archive,
            synchronization_state=state,
            capabilities=_capabilities(),
        ),
    )

    assert remaining_operations == [
        PinMessageOperation(
            message_id=desired_message.id,
            canonical_fingerprint=canonical_fingerprint(desired_message),
        ),
    ]


def test_synchronize_with_sqlite_does_not_persist_failed_operation(
    tmp_path,
) -> None:
    archive = _archive()
    destination = _destination()
    old_reaction = CanonicalReaction(
        emoji="👍",
        identity_key=IdentityKey("identity-001"),
    )
    new_reaction = CanonicalReaction(
        emoji="❤️",
        identity_key=IdentityKey("identity-001"),
    )
    old_message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=ConversationId("conversation-001"),
        identity_key=IdentityKey("identity-001"),
        content="old content",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
        pinned=False,
        reactions=(old_reaction,),
    )
    desired_message = CanonicalMessage(
        id=old_message.id,
        conversation_id=old_message.conversation_id,
        identity_key=old_message.identity_key,
        content="new content",
        created_at=old_message.created_at,
        pinned=True,
        reactions=(new_reaction,),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([])
    archive.iter_messages.side_effect = lambda: iter([desired_message])

    initial_state = SynchronizationState(
        messages={
            "message-001": DestinationMessageRef("destination-message-001"),
        },
        message_fingerprints={
            "message-001": canonical_fingerprint(old_message),
        },
        message_content_fingerprints={
            "message-001": canonical_message_content_fingerprint(old_message),
        },
        message_reactions={"message-001": (old_reaction,)},
        message_attachments={"message-001": ()},
        message_pinned={"message-001": False},
        message_reply_to={"message-001": None},
    )

    path = tmp_path / "state.sqlite3"
    with SQLiteStateRepository(path) as repository:
        repository.record_execution(
            operation=EditMessageOperation(message=old_message),
            result=ExecutionResult(canonical_id="message-001"),
            synchronization_state=initial_state,
        )

    destination.pin_message.side_effect = RuntimeError("pin failed")

    with SQLiteStateRepository(path) as repository:
        coordinator = SyncCoordinator(
            archive=archive,
            planner=Planner(),
            executor=OperationExecutor(),
            destination=destination,
            capabilities=_capabilities(),
            state_repository=repository,
        )

        with pytest.raises(RuntimeError, match="pin failed"):
            coordinator.synchronize()

    with SQLiteStateRepository(path) as repository:
        state = repository.load_synchronization_state()
        rows = repository._connection.execute(
            "SELECT operation_type, canonical_id FROM execution_log ORDER BY id",
        ).fetchall()

    assert state.message_content_fingerprints["message-001"] == (
        canonical_message_content_fingerprint(desired_message)
    )
    assert state.message_reactions["message-001"] == (new_reaction,)
    assert state.message_pinned["message-001"] is False
    assert state.message_fingerprints["message-001"] == (
        canonical_fingerprint(old_message)
    )
    assert [(row[0], row[1]) for row in rows] == [
        ("EditMessageOperation", "message-001"),
        ("EditMessageOperation", "message-001"),
        ("RemoveReactionOperation", "message-001"),
        ("AddReactionOperation", "message-001"),
    ]


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
        context=ANY,
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
        context=ANY,
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
        canonical_fingerprint=canonical_fingerprint(conversation),
        conversation_parent_id=None,
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
        fingerprint=canonical_fingerprint(conversation),
        parent_id=None,
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
        canonical_fingerprint=canonical_fingerprint(conversation_one),
        conversation_parent_id=None,
    )

    result_two = ExecutionResult(
        conversation=destination_ref_two,
        canonical_id=str(conversation_two.id),
        canonical_fingerprint=canonical_fingerprint(conversation_two),
        conversation_parent_id=None,
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
        fingerprint=canonical_fingerprint(conversation_one),
        parent_id=None,
    )

    expected_state_two = expected_state_one.with_conversation(
        canonical_id=str(conversation_two.id),
        destination_ref=destination_ref_two,
        fingerprint=canonical_fingerprint(conversation_two),
        parent_id=None,
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
        canonical_fingerprint=canonical_fingerprint(
            CanonicalConversation(
                id=ConversationId("conversation-001"),
                conversation_type=ConversationType.CHANNEL,
                title="General",
            ),
        ),
        conversation_parent_id=None,
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
        canonical_fingerprint=canonical_fingerprint(
            operation.conversation,
        ),
        conversation_parent_id=None,
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

def test_synchronize_creates_messages_then_applies_reply_using_execution_context() -> None:
    archive = _archive()
    destination = _destination()
    conversation = CanonicalConversation(
        id=ConversationId("conversation-001"),
        conversation_type=ConversationType.CHANNEL,
        title="conversation-001",
    )
    target = CanonicalMessage(
        id=MessageId("message-002"),
        conversation_id=conversation.id,
        identity_key=IdentityKey("identity-001"),
        content="Target",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
    )
    reply = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=conversation.id,
        identity_key=IdentityKey("identity-001"),
        content="Reply",
        created_at=datetime(2026, 8, 1, 12, 1, tzinfo=timezone.utc),
        reply_to=target.id,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.side_effect = lambda: iter([reply, target])

    destination.create_conversation.return_value = DestinationConversationRef(
        "destination-conversation-001",
    )
    destination.create_message.side_effect = [
        DestinationMessageRef("destination-message-001"),
        DestinationMessageRef("destination-message-002"),
    ]

    state_repository = InMemoryStateRepository()
    coordinator = SyncCoordinator(
        archive=archive,
        planner=Planner(),
        executor=OperationExecutor(),
        destination=destination,
        capabilities=_capabilities(),
        state_repository=state_repository,
    )

    coordinator.synchronize()

    destination.create_message.assert_has_calls(
        [
            call(
                replace(reply, reply_to=None),
                DestinationConversationRef("destination-conversation-001"),
            ),
            call(
                target,
                DestinationConversationRef("destination-conversation-001"),
            ),
        ],
    )
    destination.set_message_reply.assert_called_once_with(
        DestinationMessageRef("destination-message-001"),
        DestinationMessageRef("destination-message-002"),
    )

    state = state_repository.load_synchronization_state()
    assert state.message_reply_to == {
        "message-001": target.id,
        "message-002": None,
    }
    assert state.message_fingerprints["message-001"] == (
        canonical_fingerprint(reply)
    )


def test_synchronize_retries_only_failed_reply_after_partial_message_creation() -> None:
    archive = _archive()
    destination = _destination()
    conversation = CanonicalConversation(
        id=ConversationId("conversation-001"),
        conversation_type=ConversationType.CHANNEL,
        title="conversation-001",
    )
    target = CanonicalMessage(
        id=MessageId("message-002"),
        conversation_id=conversation.id,
        identity_key=IdentityKey("identity-001"),
        content="Target",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
    )
    reply = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=conversation.id,
        identity_key=IdentityKey("identity-001"),
        content="Reply",
        created_at=datetime(2026, 8, 1, 12, 1, tzinfo=timezone.utc),
        reply_to=target.id,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.side_effect = lambda: iter([reply, target])

    destination.create_conversation.return_value = DestinationConversationRef(
        "destination-conversation-001",
    )
    destination.create_message.side_effect = [
        DestinationMessageRef("destination-message-001"),
        DestinationMessageRef("destination-message-002"),
    ]
    destination.set_message_reply.side_effect = [
        RuntimeError("reply failed"),
        None,
    ]

    state_repository = InMemoryStateRepository()
    coordinator = SyncCoordinator(
        archive=archive,
        planner=Planner(),
        executor=OperationExecutor(),
        destination=destination,
        capabilities=_capabilities(),
        state_repository=state_repository,
    )

    with pytest.raises(RuntimeError, match="reply failed"):
        coordinator.synchronize()

    partial_state = state_repository.load_synchronization_state()
    assert "message-001" in partial_state.messages
    assert "message-001" not in partial_state.message_fingerprints
    assert "message-001" not in partial_state.message_reply_to

    coordinator.synchronize()

    assert destination.create_message.call_count == 2
    assert destination.set_message_reply.call_count == 2

    final_state = state_repository.load_synchronization_state()
    assert final_state.message_reply_to["message-001"] == target.id
    assert final_state.message_fingerprints["message-001"] == (
        canonical_fingerprint(reply)
    )


def test_synchronize_decomposes_initial_message_components_end_to_end(tmp_path) -> None:
    archive = _archive()
    destination = _destination()
    conversation = CanonicalConversation(
        id=ConversationId("conversation-001"),
        conversation_type=ConversationType.CHANNEL,
        title="conversation-001",
    )
    content = b"attachment content"
    attachment = CanonicalAttachment(
        id=AttachmentId("attachment-001"),
        filename="example.txt",
        content_type="text/plain",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    reaction = CanonicalReaction(
        identity_key=IdentityKey("identity-001"),
        emoji="👍",
    )
    message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=conversation.id,
        identity_key=IdentityKey("identity-001"),
        content="Hello",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
        attachments=(attachment,),
        reactions=(reaction,),
        pinned=True,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.return_value = iter([message])

    destination.create_conversation.return_value = DestinationConversationRef(
        "destination-conversation-001",
    )
    destination.create_message.return_value = DestinationMessageRef(
        "destination-message-001",
    )

    asset_store = AssetStore(tmp_path)
    asset_store.put_attachment(attachment, content)

    state_repository = InMemoryStateRepository()
    coordinator = SyncCoordinator(
        archive=archive,
        planner=Planner(),
        executor=OperationExecutor(asset_store=asset_store),
        destination=destination,
        capabilities=_capabilities(),
        state_repository=state_repository,
    )

    coordinator.synchronize()

    destination.create_message.assert_called_once_with(
        replace(
            message,
            attachments=(),
            reactions=(),
            pinned=False,
            reply_to=None,
        ),
        DestinationConversationRef("destination-conversation-001"),
    )
    destination.add_attachment.assert_called_once_with(
        DestinationMessageRef("destination-message-001"),
        attachment,
        content,
    )
    destination.add_reaction.assert_called_once_with(
        DestinationMessageRef("destination-message-001"),
        reaction,
    )
    destination.pin_message.assert_called_once_with(DestinationMessageRef("destination-message-001"))

    state = state_repository.load_synchronization_state()
    assert state.message_fingerprints["message-001"] == canonical_fingerprint(
        message,
    )
    assert state.message_content_fingerprints["message-001"] == (
        canonical_message_content_fingerprint(message)
    )
    assert state.message_attachments["message-001"] == (attachment,)
    assert state.message_reactions["message-001"] == (reaction,)
    assert state.message_pinned["message-001"] is True
    assert state.message_reply_to["message-001"] is None


def test_synchronize_retries_only_remaining_initial_message_components(
    tmp_path,
) -> None:
    archive = _archive()
    destination = _destination()
    conversation = CanonicalConversation(
        id=ConversationId("conversation-001"),
        conversation_type=ConversationType.CHANNEL,
        title="conversation-001",
    )
    content = b"attachment content"
    attachment = CanonicalAttachment(
        id=AttachmentId("attachment-001"),
        filename="example.txt",
        content_type="text/plain",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    reaction = CanonicalReaction(
        identity_key=IdentityKey("identity-001"),
        emoji="👍",
    )
    message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=conversation.id,
        identity_key=IdentityKey("identity-001"),
        content="Hello",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
        attachments=(attachment,),
        reactions=(reaction,),
        pinned=True,
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.side_effect = lambda: iter([message])

    destination.create_conversation.return_value = DestinationConversationRef(
        "destination-conversation-001",
    )
    destination.create_message.return_value = DestinationMessageRef(
        "destination-message-001",
    )
    destination.pin_message.side_effect = [
        RuntimeError("pin failed"),
        None,
    ]

    asset_store = AssetStore(tmp_path)
    asset_store.put_attachment(attachment, content)
    state_repository = InMemoryStateRepository()
    coordinator = SyncCoordinator(
        archive=archive,
        planner=Planner(),
        executor=OperationExecutor(asset_store=asset_store),
        destination=destination,
        capabilities=_capabilities(),
        state_repository=state_repository,
    )

    with pytest.raises(RuntimeError, match="pin failed"):
        coordinator.synchronize()

    partial_state = state_repository.load_synchronization_state()
    assert partial_state.messages["message-001"] == DestinationMessageRef(
        "destination-message-001",
    )
    assert partial_state.message_attachments["message-001"] == (attachment,)
    assert partial_state.message_reactions["message-001"] == (reaction,)
    assert partial_state.message_pinned.get("message-001") is None
    assert "message-001" not in partial_state.message_fingerprints

    coordinator.synchronize()

    assert destination.create_message.call_count == 1
    assert destination.add_attachment.call_count == 1
    assert destination.add_reaction.call_count == 1
    assert destination.pin_message.call_count == 2

    final_state = state_repository.load_synchronization_state()
    assert final_state.message_attachments["message-001"] == (attachment,)
    assert final_state.message_reactions["message-001"] == (reaction,)
    assert final_state.message_pinned["message-001"] is True
    assert final_state.message_fingerprints["message-001"] == (
        canonical_fingerprint(message)
    )



def test_synchronize_retries_only_failed_initial_attachment(tmp_path) -> None:
    archive = _archive()
    destination = _destination()
    conversation = CanonicalConversation(
        id=ConversationId("conversation-001"),
        conversation_type=ConversationType.CHANNEL,
        title="conversation-001",
    )
    content = b"attachment content"
    attachment = CanonicalAttachment(
        id=AttachmentId("attachment-001"),
        filename="example.txt",
        content_type="text/plain",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    message = CanonicalMessage(
        id=MessageId("message-001"),
        conversation_id=conversation.id,
        identity_key=IdentityKey("identity-001"),
        content="Hello",
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
        attachments=(attachment,),
    )

    archive.iter_identities.return_value = iter([])
    archive.iter_conversations.return_value = iter([conversation])
    archive.iter_messages.side_effect = lambda: iter([message])

    destination.create_conversation.return_value = DestinationConversationRef(
        "destination-conversation-001",
    )
    destination.create_message.return_value = DestinationMessageRef(
        "destination-message-001",
    )
    destination.add_attachment.side_effect = [
        RuntimeError("attachment failed"),
        None,
    ]

    asset_store = AssetStore(tmp_path)
    asset_store.put_attachment(attachment, content)
    state_repository = InMemoryStateRepository()
    coordinator = SyncCoordinator(
        archive=archive,
        planner=Planner(),
        executor=OperationExecutor(asset_store=asset_store),
        destination=destination,
        capabilities=_capabilities(),
        state_repository=state_repository,
    )

    with pytest.raises(RuntimeError, match="attachment failed"):
        coordinator.synchronize()

    partial_state = state_repository.load_synchronization_state()
    assert "message-001" in partial_state.messages
    assert "message-001" not in partial_state.message_attachments
    assert "message-001" not in partial_state.message_fingerprints

    coordinator.synchronize()

    assert destination.create_message.call_count == 1
    assert destination.add_attachment.call_count == 2

    final_state = state_repository.load_synchronization_state()
    assert final_state.message_attachments["message-001"] == (attachment,)
    assert final_state.message_fingerprints["message-001"] == (
        canonical_fingerprint(message)
    )


def test_synchronize_stops_at_failed_checkpoint_and_does_not_execute_next_operation() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()

    initial_state = SynchronizationState()
    state_repository.load_synchronization_state.return_value = initial_state

    operation_one = Mock(spec=SyncOperation)
    operation_two = Mock(spec=SyncOperation)

    planner.plan.return_value = iter((operation_one, operation_two))
    executor.execute.return_value = ExecutionResult(
        canonical_id="message-001",
    )
    state_repository.record_execution.side_effect = RuntimeError(
        "checkpoint persistence failed",
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
        match="checkpoint persistence failed",
    ):
        coordinator.synchronize()

    executor.execute.assert_called_once_with(
        operation=operation_one,
        destination=destination,
        context=ANY,
    )
    state_repository.record_execution.assert_called_once()


def test_synchronize_does_not_expose_checkpoint_state_after_repository_failure() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()

    state_repository = InMemoryStateRepository()
    initial_state = SynchronizationState()
    state_repository._synchronization_state = initial_state

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
        canonical_id="conversation-001",
        conversation=destination_ref,
        canonical_fingerprint="conversation-fingerprint",
        conversation_parent_id=None,
    )

    planner.plan.return_value = iter((operation,))
    executor.execute.return_value = result

    original_record_execution = state_repository.record_execution

    def fail_checkpoint(*args, **kwargs):
        raise RuntimeError("checkpoint persistence failed")

    state_repository.record_execution = fail_checkpoint

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
        match="checkpoint persistence failed",
    ):
        coordinator.synchronize()

    assert state_repository.load_synchronization_state() is initial_state

    # Restore the repository implementation to verify that the state was
    # never replaced before the failed checkpoint.
    state_repository.record_execution = original_record_execution


def test_dry_run_plans_operations_without_executing_or_persisting_state() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()

    state = SynchronizationState()
    operation_one = Mock(spec=SyncOperation)
    operation_two = Mock(spec=SyncOperation)
    state_repository.load_synchronization_state.return_value = state
    planner.plan.return_value = iter((operation_one, operation_two))

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    assert coordinator.dry_run() == (operation_one, operation_two)
    state_repository.load_synchronization_state.assert_called_once_with()
    planner.plan.assert_called_once_with(
        archive=archive,
        synchronization_state=state,
        capabilities=capabilities,
    )
    executor.execute.assert_not_called()
    state_repository.record_execution.assert_not_called()


def test_synchronize_reports_progress_for_each_operation() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()
    reported = []

    state = SynchronizationState()
    state_repository.load_synchronization_state.return_value = state

    operation_one = CreateConversationOperation(
        conversation=CanonicalConversation(
            id=ConversationId("conversation-1"),
            conversation_type=ConversationType.CHANNEL,
            title="general",
        )
    )
    operation_two = CreateMessageOperation(
        message=CanonicalMessage(
            id=MessageId("message-1"),
            conversation_id=ConversationId("conversation-1"),
            identity_key=IdentityKey("identity-1"),
            content="hello",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    planner.plan.return_value = iter((operation_one, operation_two))
    executor.execute.side_effect = [ExecutionResult(), ExecutionResult()]

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
        on_status=reported.append,
    )

    coordinator.synchronize()

    assert [(event.phase, event.current, event.detail) for event in reported] == [
        ("conversations", 1, "conversation-1"),
        ("messages", 1, "message-1"),
    ]


def test_export_rate_limiter_applies_message_and_channel_delays() -> None:
    """Destination operations honor the configured migration delays."""
    from archive_sync_engine.adapters.references import DestinationConversationRef
    from archive_sync_engine.models import CanonicalIdentity
    from archive_sync_engine.operations import CreateConversationOperation, CreateMessageOperation
    from archive_sync_engine.rate_limit import OperationRateLimiter
    from archive_sync_engine.executor.result import ExecutionResult

    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    state_repository = Mock(spec=StateRepository)
    state_repository.load_synchronization_state.return_value = SynchronizationState()
    state_repository.record_execution.return_value = None

    conversation_one = CanonicalConversation(
        id=ConversationId("conversation-1"),
        conversation_type=ConversationType.CHANNEL,
        title="one",
    )
    conversation_two = replace(conversation_one, id=ConversationId("conversation-2"), title="two")
    identity = IdentityKey("identity-1")
    messages = (
        CanonicalMessage(
            id=MessageId("message-1"),
            conversation_id=conversation_one.id,
            identity_key=identity,
            content="one",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        CanonicalMessage(
            id=MessageId("message-2"),
            conversation_id=conversation_one.id,
            identity_key=identity,
            content="two",
            created_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        ),
        CanonicalMessage(
            id=MessageId("message-3"),
            conversation_id=conversation_two.id,
            identity_key=identity,
            content="three",
            created_at=datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
        ),
    )
    operations = [
        CreateConversationOperation(conversation_one),
        CreateMessageOperation(messages[0]),
        CreateMessageOperation(messages[1]),
        CreateConversationOperation(conversation_two),
        CreateMessageOperation(messages[2]),
    ]
    planner.plan.return_value = iter(operations)
    executor.execute.side_effect = [
        ExecutionResult(canonical_id=None),
        ExecutionResult(canonical_id=None),
        ExecutionResult(canonical_id=None),
        ExecutionResult(canonical_id=None),
        ExecutionResult(canonical_id=None),
    ]

    sleeps: list[float] = []
    limiter = OperationRateLimiter(
        between_messages_seconds=0.5,
        between_channels_seconds=2.0,
        sleep=sleeps.append,
        monotonic=lambda: 100.0,
    )

    SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=DestinationCapabilities(),
        state_repository=state_repository,
        rate_limiter=limiter,
    ).synchronize()

    assert sleeps == [2.0, 0.5]


def test_synchronize_compatibility_mode_skips_authorization_failure_and_continues() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()
    state = SynchronizationState()

    message = CanonicalMessage(
        id=MessageId("message-1"),
        conversation_id=ConversationId("conversation-1"),
        identity_key=IdentityKey("identity-1"),
        content="updated",
        attachments=(),
        created_at=datetime.now(timezone.utc),
    )
    operation = EditMessageOperation(
        message=message,
        canonical_fingerprint=canonical_fingerprint(message),
    )
    executor.execute.side_effect = [
        __import__("archive_sync_engine.adapters.exceptions", fromlist=["AuthorizationError"]).AuthorizationError(
            "Fluxer message cannot be edited by the authenticated identity."
        ),
        ExecutionResult(canonical_id="conversation-1"),
    ]
    second_operation = Mock()
    planner.plan.return_value = iter((operation, second_operation))
    state_repository.load_synchronization_state.return_value = state

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
        compatibility_mode=True,
    )

    results = coordinator.synchronize()

    assert len(results) == 2
    assert results[0].skipped is True
    assert results[0].canonical_id == "message-1"
    assert results[1].canonical_id == "conversation-1"
    assert executor.execute.call_count == 2
    assert state_repository.record_execution.call_count == 2


def test_synchronize_strict_mode_propagates_authorization_failure() -> None:
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()
    state_repository.load_synchronization_state.return_value = SynchronizationState()
    planner.plan.return_value = iter(())

    from archive_sync_engine.adapters.exceptions import AuthorizationError
    executor.execute.side_effect = AuthorizationError("forbidden")
    planner.plan.return_value = iter((Mock(),))

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    with pytest.raises(AuthorizationError, match="forbidden"):
        coordinator.synchronize()


def test_synchronize_non_compatibility_mode_propagates_authorization_failure() -> None:
    """Normal synchronization must not hide authorization failures."""
    archive = _archive()
    planner = _planner()
    executor = _executor()
    destination = _destination()
    capabilities = _capabilities()
    state_repository = _state_repository()
    state_repository.load_synchronization_state.return_value = SynchronizationState()
    operation = Mock(spec=SyncOperation)
    planner.plan.return_value = iter((operation,))
    error = AuthorizationError("cannot edit another user's message")
    executor.execute.side_effect = error

    coordinator = SyncCoordinator(
        archive=archive,
        planner=planner,
        executor=executor,
        destination=destination,
        capabilities=capabilities,
        state_repository=state_repository,
    )

    with pytest.raises(AuthorizationError, match="cannot edit"):
        coordinator.synchronize()

    state_repository.record_execution.assert_not_called()
