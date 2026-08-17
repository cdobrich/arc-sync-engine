from __future__ import annotations

from archive_sync_engine.adapters.capability_validation import validate_adapter_capabilities


def test_default_adapter_capabilities_are_valid() -> None:
    report = validate_adapter_capabilities()
    assert report.valid is True
    assert report.errors == ()


def test_source_adapter_without_runtime_is_reported(monkeypatch) -> None:
    from archive_sync_engine.adapters.registry import AdapterDescriptor, AdapterRegistry
    from archive_sync_engine.adapters import capability_validation

    monkeypatch.setattr(
        capability_validation,
        "default_adapter_registry",
        lambda: AdapterRegistry((AdapterDescriptor("future", source=True),)),
    )
    monkeypatch.setattr(capability_validation, "default_source_runtime_registry", lambda: type("R", (), {"names": lambda self: ()})())
    monkeypatch.setattr(capability_validation, "default_destination_runtime_registry", lambda: type("R", (), {"names": lambda self: ()})())
    monkeypatch.setattr(capability_validation, "default_sync_pair_registry", lambda: type("R", (), {"list": lambda self: ()})())
    monkeypatch.setattr(capability_validation, "default_sync_runtime_registry", lambda: type("R", (), {"keys": lambda self: ()})())

    report = validate_adapter_capabilities()
    assert report.valid is False
    assert "has no source runtime" in report.errors[0]


def test_sync_pair_without_runtime_is_reported(monkeypatch) -> None:
    from archive_sync_engine.adapters import capability_validation
    from archive_sync_engine.adapters.sync_registry import SyncPairDescriptor

    monkeypatch.setattr(capability_validation, "default_adapter_registry", lambda: type("R", (), {"list": lambda self: ()})())
    monkeypatch.setattr(capability_validation, "default_source_runtime_registry", lambda: type("R", (), {"names": lambda self: ()})())
    monkeypatch.setattr(capability_validation, "default_destination_runtime_registry", lambda: type("R", (), {"names": lambda self: ()})())
    monkeypatch.setattr(capability_validation, "default_sync_pair_registry", lambda: type("R", (), {"list": lambda self: (SyncPairDescriptor("a", "b"),)})())
    monkeypatch.setattr(capability_validation, "default_sync_runtime_registry", lambda: type("R", (), {"keys": lambda self: ()})())

    report = validate_adapter_capabilities()
    assert report.valid is False
    assert "has no synchronization runtime" in report.errors[0]


def test_sync_runtime_without_pair_is_reported(monkeypatch) -> None:
    from archive_sync_engine.adapters import capability_validation

    monkeypatch.setattr(capability_validation, "default_adapter_registry", lambda: type("R", (), {"list": lambda self: ()})())
    monkeypatch.setattr(capability_validation, "default_source_runtime_registry", lambda: type("R", (), {"names": lambda self: ()})())
    monkeypatch.setattr(capability_validation, "default_destination_runtime_registry", lambda: type("R", (), {"names": lambda self: ()})())
    monkeypatch.setattr(capability_validation, "default_sync_pair_registry", lambda: type("R", (), {"list": lambda self: ()})())
    monkeypatch.setattr(capability_validation, "default_sync_runtime_registry", lambda: type("R", (), {"keys": lambda self: (("a", "b"),)})())

    report = validate_adapter_capabilities()
    assert report.valid is False
    assert "has no supported sync pair" in report.errors[0]
