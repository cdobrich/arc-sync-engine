from pathlib import Path

import pytest

from archive_sync_engine.sync.state_path import synchronization_state_path


def test_synchronization_state_path_is_scoped_by_adapter_and_scope(tmp_path: Path) -> None:
    first = synchronization_state_path(
        tmp_path, adapter="fluxer", scope=("guild-1",)
    )
    second = synchronization_state_path(
        tmp_path, adapter="fluxer", scope=("guild-2",)
    )
    discord = synchronization_state_path(
        tmp_path, adapter="discord", scope=("guild-1",)
    )

    assert first != second
    assert first != discord
    assert first.parent == tmp_path / "synchronization" / "fluxer"
    assert first.suffix == ".sqlite"


def test_synchronization_state_path_rejects_empty_scope(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        synchronization_state_path(tmp_path, adapter="fluxer", scope=())

    with pytest.raises(ValueError):
        synchronization_state_path(tmp_path, adapter="fluxer", scope=("",))

def test_synchronization_state_path_is_stable_for_the_same_destination(tmp_path: Path) -> None:
    first = synchronization_state_path(
        tmp_path, adapter="fluxer", scope=("1539964012871808",)
    )
    second = synchronization_state_path(
        tmp_path, adapter="fluxer", scope=("1539964012871808",)
    )

    assert first == second


def test_synchronization_state_path_changes_when_scope_changes(tmp_path: Path) -> None:
    first = synchronization_state_path(
        tmp_path, adapter="fluxer", scope=("1539964012871808",)
    )
    second = synchronization_state_path(
        tmp_path, adapter="fluxer", scope=("1539964012871809",)
    )

    assert first != second

