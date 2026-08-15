from __future__ import annotations

import pytest

from archive_sync_engine.adapters import SourceRuntimeRegistry


def test_source_runtime_registry_resolves_registered_runtime_factory() -> None:
    registry = SourceRuntimeRegistry()
    factory = object()

    registry.register("Example", factory)  # type: ignore[arg-type]

    assert registry.names() == ("example",)
    assert registry.resolve("EXAMPLE") is factory


def test_source_runtime_registry_rejects_duplicate_names() -> None:
    registry = SourceRuntimeRegistry()
    registry.register("example", lambda _args: object())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="already registered"):
        registry.register("EXAMPLE", lambda _args: object())  # type: ignore[arg-type]


def test_source_runtime_registry_reports_unknown_adapter_and_available_names() -> None:
    registry = SourceRuntimeRegistry()
    registry.register("discord", lambda _args: object())  # type: ignore[arg-type]
    registry.register("fluxer", lambda _args: object())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Available adapters: discord, fluxer"):
        registry.resolve("matrix")
