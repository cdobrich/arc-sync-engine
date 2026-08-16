from __future__ import annotations
import pytest
from archive_sync_engine.sync.runtime_registry import SyncRuntimeRegistry, default_sync_runtime_registry

def test_runtime_registry_normalizes_and_creates() -> None:
    registry = SyncRuntimeRegistry()
    registry.register(" Discord ", " Fluxer ", lambda config: {"config": config})
    assert registry.create("DISCORD", "FLUXER", "configuration") == {"config": "configuration"}

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
    assert registry.create("discord", "fluxer", object()) is marker
