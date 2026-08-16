from pathlib import Path

import pytest

from archive_sync_engine.adapters import (
    DestinationRuntimeRegistry,
    DestinationRuntimeRequest,
    default_destination_runtime_registry,
)


def test_destination_runtime_registry_normalizes_names_and_creates_runtime(tmp_path: Path) -> None:
    captured: list[DestinationRuntimeRequest] = []

    def factory(request: DestinationRuntimeRequest) -> object:
        captured.append(request)
        return object()

    registry = DestinationRuntimeRegistry({" Fluxer ": factory})
    request = DestinationRuntimeRequest("FLUXER", ("server",), tmp_path, {})

    runtime = registry.create("fluxer", request)

    assert runtime is not None
    assert captured == [request]
    assert registry.names() == ("fluxer",)


def test_destination_runtime_registry_rejects_duplicate_registration() -> None:
    registry = DestinationRuntimeRegistry()
    registry.register("fluxer", lambda request: request)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(" FLUXER ", lambda request: request)


def test_destination_runtime_registry_rejects_unknown_adapter() -> None:
    registry = DestinationRuntimeRegistry()

    with pytest.raises(ValueError, match="Unknown destination adapter"):
        registry.resolve("discord")


def test_destination_runtime_registry_rejects_mismatched_request(tmp_path: Path) -> None:
    registry = DestinationRuntimeRegistry({"fluxer": lambda request: request})
    request = DestinationRuntimeRequest("discord", ("server",), tmp_path, {})

    with pytest.raises(ValueError, match="does not match"):
        registry.create("fluxer", request)


def test_default_destination_runtime_registry_registers_fluxer() -> None:
    registry = default_destination_runtime_registry(fluxer_factory=lambda request: request)

    assert registry.names() == ("fluxer",)
