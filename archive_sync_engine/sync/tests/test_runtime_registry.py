from __future__ import annotations
import pytest
from pathlib import Path

from archive_sync_engine.sync.runtime_registry import SyncRuntimeRegistry, default_sync_runtime_registry
from archive_sync_engine.sync.runtime_request import SyncRuntimeRequest

def test_runtime_registry_normalizes_and_creates() -> None:
    registry = SyncRuntimeRegistry()
    registry.register(" Discord ", " Fluxer ", lambda config: {"config": config})
    request = SyncRuntimeRequest(
        input_adapter="discord",
        input_scope=("1",),
        destination_adapter="fluxer",
        destination_scope=("2",),
        archive_path=Path("archive"),
        adapter_config={},
    )
    assert registry.create("DISCORD", "FLUXER", request) == {"config": request}

def test_runtime_registry_rejects_duplicate_pair() -> None:
    registry = SyncRuntimeRegistry()
    registry.register("discord", "fluxer", lambda config: config)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("DISCORD", "FLUXER", lambda config: config)

def test_runtime_registry_reports_unknown_pair() -> None:
    registry = SyncRuntimeRegistry()
    registry.register("discord", "fluxer", lambda config: config)
    with pytest.raises(ValueError, match="No synchronization runtime"):
        registry.resolve("fluxer", "fluxer")

def test_runtime_registry_rejects_non_callable_factory() -> None:
    registry = SyncRuntimeRegistry()
    with pytest.raises(TypeError, match="must be callable"):
        registry.register("discord", "fluxer", object())  # type: ignore[arg-type]

def test_default_runtime_registry_is_injectable() -> None:
    marker = object()
    registry = default_sync_runtime_registry(lambda config: marker)
    assert registry.keys() == (("discord", "fluxer"),)
    request = SyncRuntimeRequest(
        input_adapter="discord",
        input_scope=("1",),
        destination_adapter="fluxer",
        destination_scope=("2",),
        archive_path=Path("archive"),
        adapter_config={},
    )
    assert registry.create("discord", "fluxer", request) is marker


def test_runtime_registry_rejects_mismatched_request_pair() -> None:
    registry = SyncRuntimeRegistry()
    registry.register("discord", "fluxer", lambda request: request)
    request = SyncRuntimeRequest(
        input_adapter="fluxer",
        input_scope=("1",),
        destination_adapter="fluxer",
        destination_scope=("2",),
        archive_path=Path("archive"),
        adapter_config={},
    )
    with pytest.raises(ValueError, match="does not match"):
        registry.create("discord", "fluxer", request)
