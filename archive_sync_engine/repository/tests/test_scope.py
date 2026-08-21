from pathlib import Path

from archive_sync_engine.repository.scope import synchronization_state_path


def test_synchronization_state_path_is_distinct_per_destination_scope(tmp_path: Path) -> None:
    first = synchronization_state_path(
        tmp_path,
        adapter="fluxer",
        scope=("1514424954370920478",),
    )
    second = synchronization_state_path(
        tmp_path,
        adapter="fluxer",
        scope=("1513385837872549939",),
    )

    assert first != second
    assert first.name.startswith("synchronization.fluxer.1514424954370920478.")
    assert second.name.startswith("synchronization.fluxer.1513385837872549939.")


def test_scoped_state_repositories_do_not_share_destination_mappings(tmp_path: Path) -> None:
    from archive_sync_engine.adapters.references import DestinationConversationRef
    from archive_sync_engine.executor import ExecutionResult
    from archive_sync_engine.operations import EditMessageOperation
    from archive_sync_engine.repository import SQLiteStateRepository
    from archive_sync_engine.sync import SynchronizationState
    from unittest.mock import Mock

    first_path = synchronization_state_path(
        tmp_path, adapter="fluxer", scope=("guild-a",)
    )
    second_path = synchronization_state_path(
        tmp_path, adapter="fluxer", scope=("guild-b",)
    )

    state = SynchronizationState(
        conversations={
            "conversation-1": DestinationConversationRef("guild-a-channel"),
        },
    )
    with SQLiteStateRepository(first_path) as repository:
        repository.record_execution(
            EditMessageOperation(message=Mock()),
            ExecutionResult(canonical_id="message-1"),
            state,
        )

    with SQLiteStateRepository(first_path) as repository:
        assert repository.load_synchronization_state() == state
    with SQLiteStateRepository(second_path) as repository:
        assert repository.load_synchronization_state() == SynchronizationState()
