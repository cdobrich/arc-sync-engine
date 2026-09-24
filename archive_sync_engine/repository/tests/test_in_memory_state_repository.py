"""
Tests for the in-memory StateRepository implementation.
"""

from __future__ import annotations

from unittest.mock import Mock

from archive_sync_engine.executor import ExecutionResult
from archive_sync_engine.importer import ImportSession
from archive_sync_engine.operations import SyncOperation
from archive_sync_engine.repository import InMemoryStateRepository
from archive_sync_engine.sync import SynchronizationState


def test_load_synchronization_state_returns_initial_state() -> None:
    state = SynchronizationState()

    repository = InMemoryStateRepository(
        synchronization_state=state,
    )

    assert repository.load_synchronization_state() is state


def test_load_synchronization_state_defaults_to_empty_state() -> None:
    repository = InMemoryStateRepository()

    state = repository.load_synchronization_state()

    assert state == SynchronizationState()


def test_record_execution_replaces_synchronization_state() -> None:
    repository = InMemoryStateRepository()

    operation = Mock(
        spec=SyncOperation,
    )

    result = Mock(
        spec=ExecutionResult,
    )

    new_state = SynchronizationState(
        conversations={
            "conversation-001": Mock(),
        },
    )

    repository.record_execution(
        operation=operation,
        result=result,
        synchronization_state=new_state,
    )

    assert repository.load_synchronization_state() is new_state


def test_record_execution_does_not_mutate_previous_state() -> None:
    initial_state = SynchronizationState()

    repository = InMemoryStateRepository(
        synchronization_state=initial_state,
    )

    operation = Mock(
        spec=SyncOperation,
    )

    result = Mock(
        spec=ExecutionResult,
    )

    new_state = SynchronizationState(
        messages={
            "message-001": Mock(),
        },
    )

    repository.record_execution(
        operation=operation,
        result=result,
        synchronization_state=new_state,
    )

    assert initial_state == SynchronizationState()
    assert repository.load_synchronization_state() is new_state


def test_save_and_load_import_session() -> None:
    repository = InMemoryStateRepository()

    session = Mock(
        spec=ImportSession,
    )

    repository.save_import_session(
        session,
    )

    assert repository.load_import_session() is session


def test_load_import_session_returns_none_initially() -> None:
    repository = InMemoryStateRepository()

    assert repository.load_import_session() is None

def test_query_execution_log_returns_newest_first_and_supports_filters() -> None:
    repository = InMemoryStateRepository()

    repository.record_execution(
        operation=Mock(spec=SyncOperation),
        result=ExecutionResult(canonical_id="message-001"),
        synchronization_state=SynchronizationState(),
    )
    repository.record_execution(
        operation=Mock(spec=SyncOperation),
        result=ExecutionResult(canonical_id="message-002"),
        synchronization_state=SynchronizationState(),
    )

    entries = repository.query_execution_log()

    assert [entry.canonical_id for entry in entries] == [
        "message-002",
        "message-001",
    ]
    assert [entry.id for entry in entries] == [2, 1]

    assert [
        entry.canonical_id
        for entry in repository.query_execution_log(canonical_id="message-001")
    ] == ["message-001"]


def test_query_execution_log_rejects_negative_limit() -> None:
    repository = InMemoryStateRepository()

    try:
        repository.query_execution_log(limit=-1)
    except ValueError as exc:
        assert "limit" in str(exc)
    else:
        raise AssertionError("Expected negative limit to be rejected.")


def test_save_synchronization_state_replaces_snapshot_without_execution_log() -> None:
    repository = InMemoryStateRepository()
    state = SynchronizationState(
        conversations={"conversation-1": Mock()},
    )

    repository.save_synchronization_state(state)

    assert repository.load_synchronization_state() is state
    assert repository.query_execution_log() == ()
