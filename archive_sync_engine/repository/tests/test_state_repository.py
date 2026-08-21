

def test_synchronization_state_path_is_stable_and_destination_scoped(tmp_path):
    from archive_sync_engine.repository import synchronization_state_path

    first = synchronization_state_path(
        tmp_path,
        adapter="fluxer",
        scope=("guild-1",),
    )
    second = synchronization_state_path(
        tmp_path,
        adapter="fluxer",
        scope=("guild-2",),
    )
    repeat = synchronization_state_path(
        tmp_path,
        adapter="fluxer",
        scope=("guild-1",),
    )

    assert first == repeat
    assert first != second
    assert first.parent == tmp_path
    assert first.name.startswith("synchronization-fluxer-")
