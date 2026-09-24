from __future__ import annotations

import pytest

from archive_sync_engine.adapters import (
    AdapterDescriptor,
    AdapterRegistry,
    default_adapter_registry,
)


def test_default_registry_exposes_platform_roles_without_coupling_core_workflows() -> None:
    registry = default_adapter_registry()

    assert registry.require_source("DISCORD").name == "discord"
    assert registry.require_destination("Fluxer").name == "fluxer"
    assert registry.list() == (
        registry.get("discord"),
        registry.get("fluxer"),
    )


def test_registry_supports_future_adapter_registration() -> None:
    registry = AdapterRegistry()
    registry.register(
        AdapterDescriptor(
            name="future-platform",
            source=True,
            destination=True,
            description="Test future platform.",
        )
    )

    assert registry.require_source("future-platform").destination is True
    assert registry.require_destination("future-platform").source is True


def test_registry_rejects_unknown_and_wrong_role_adapters() -> None:
    registry = default_adapter_registry()

    with pytest.raises(ValueError, match="Unknown adapter"):
        registry.get("matrix")
    assert registry.require_source("fluxer").name == "fluxer"
    with pytest.raises(ValueError, match="does not support destination"):
        registry.require_destination("discord")


def test_registry_rejects_duplicate_and_roleless_descriptors() -> None:
    with pytest.raises(ValueError, match="source or destination"):
        AdapterDescriptor(name="empty")

    registry = AdapterRegistry((AdapterDescriptor(name="discord", source=True),))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(AdapterDescriptor(name="DISCORD", source=True))
