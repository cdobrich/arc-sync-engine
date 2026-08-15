from __future__ import annotations

import pytest

from archive_sync_engine.sync.run_configuration import (
    RunDirection,
    SyncRunConfiguration,
)


def test_run_configuration_round_trips_generic_input_and_destination_adapters() -> None:
    configuration = SyncRunConfiguration(
        direction=RunDirection.SYNC,
        input_adapter="Fluxer",
        input_scope=("source-guild-1",),
        destination_adapter="Discord",
        destination_scope=("target-guild-2",),
    )

    restored = SyncRunConfiguration.from_json_dict(configuration.to_json_dict())

    assert restored == SyncRunConfiguration(
        direction=RunDirection.SYNC,
        input_adapter="fluxer",
        input_scope=("source-guild-1",),
        destination_adapter="discord",
        destination_scope=("target-guild-2",),
    )


def test_run_configuration_rejects_empty_adapter_names() -> None:
    with pytest.raises(ValueError, match="Input adapter"):
        SyncRunConfiguration(direction=RunDirection.IMPORT, input_adapter=" ")

    with pytest.raises(ValueError, match="Destination adapter"):
        SyncRunConfiguration(
            direction=RunDirection.SYNC,
            input_adapter="discord",
            destination_adapter=" ",
        )


def test_run_configuration_rejects_empty_scope_values() -> None:
    with pytest.raises(ValueError, match="Input scope"):
        SyncRunConfiguration(
            direction=RunDirection.IMPORT,
            input_adapter="fluxer",
            input_scope=("",),
        )


def test_run_configuration_contains_no_credentials() -> None:
    configuration = SyncRunConfiguration(
        direction=RunDirection.SYNC,
        input_adapter="discord",
        input_scope=("123",),
        destination_adapter="fluxer",
        destination_scope=("456",),
    )

    serialized = configuration.to_json_dict()

    assert "token" not in serialized
    assert "auth_key" not in serialized
    assert "password" not in serialized
