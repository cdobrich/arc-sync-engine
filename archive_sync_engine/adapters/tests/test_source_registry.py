from __future__ import annotations

import pytest

from archive_sync_engine.adapters import SourceRuntimeRegistry


def test_source_runtime_registry_resolves_registered_factory() -> None:
    class Runtime:
        def __init__(self, value: str) -> None:
            self.value = value

    registry = SourceRuntimeRegistry()
    registry.register(" Example ", Runtime)

    assert registry.resolve("EXAMPLE") is Runtime
    assert registry.create("example", "ok").value == "ok"
    assert registry.names() == ("example",)


def test_source_runtime_registry_rejects_duplicate_names() -> None:
    registry = SourceRuntimeRegistry()
    registry.register("discord", object)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("DISCORD", object)


def test_source_runtime_registry_rejects_unknown_source() -> None:
    registry = SourceRuntimeRegistry()

    with pytest.raises(ValueError, match="Unknown source adapter"):
        registry.resolve("fluxer")
