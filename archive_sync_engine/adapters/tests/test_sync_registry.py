from __future__ import annotations

import pytest

from archive_sync_engine.adapters import (
    SyncPairDescriptor,
    SyncPairRegistry,
    default_sync_pair_registry,
)


def test_sync_pair_registry_normalizes_adapter_names() -> None:
    registry = SyncPairRegistry(
        (SyncPairDescriptor(" Discord ", " FLUXER "),)
    )

    pair = registry.get("discord", "fluxer")

    assert pair.input_adapter == "discord"
    assert pair.destination_adapter == "fluxer"


def test_sync_pair_registry_rejects_duplicate_pairs() -> None:
    registry = SyncPairRegistry((SyncPairDescriptor("discord", "fluxer"),))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(SyncPairDescriptor("DISCORD", "FLUXER"))


def test_sync_pair_registry_reports_unknown_pair() -> None:
    registry = default_sync_pair_registry()

    with pytest.raises(ValueError, match="Unsupported sync adapter pair"):
        registry.get("fluxer", "fluxer")


def test_default_registry_keeps_platform_pairing_out_of_generic_adapter_registry() -> None:
    pairs = default_sync_pair_registry().list()

    assert [(pair.input_adapter, pair.destination_adapter) for pair in pairs] == [
        ("discord", "fluxer")
    ]
