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