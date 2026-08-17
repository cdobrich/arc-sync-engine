from pathlib import Path

import pytest

from archive_sync_engine.adapters import SourceRuntimeRegistry, SourceRuntimeRequest


def request(tmp_path: Path, adapter: str = "discord") -> SourceRuntimeRequest:
    return SourceRuntimeRequest(adapter, ("123",), tmp_path, {})


def test_source_runtime_registry_creates_from_request(tmp_path: Path) -> None:
    registry = SourceRuntimeRegistry()
    marker = object()
    registry.register("Discord", lambda request: marker)

    assert registry.create(" discord ", request(tmp_path)) is marker


def test_source_runtime_registry_rejects_mismatched_request(tmp_path: Path) -> None:
    registry = SourceRuntimeRegistry({"discord": lambda request: object()})

    with pytest.raises(ValueError, match="does not match"):
        registry.create("discord", request(tmp_path, "fluxer"))


def test_default_source_runtime_registry_uses_adapter_neutral_factory() -> None:
    registry = __import__(
        "archive_sync_engine.adapters.source_registry",
        fromlist=["default_source_runtime_registry"],
    ).default_source_runtime_registry(lambda request: request)

    assert registry.names() == ("discord",)


def test_source_runtime_registry_builds_adapter_specific_config() -> None:
    registry = SourceRuntimeRegistry(
        {"example": lambda request: request},
        {"example": lambda credentials, scope, overrides: (credentials, scope, overrides)},
    )

    assert registry.build_config("example", "credentials", ("scope",), {"option": 1}) == (
        "credentials",
        ("scope",),
        {"option": 1},
    )
