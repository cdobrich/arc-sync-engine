from archive_sync_engine.adapters import (
    AdapterDescriptor,
    AdapterRegistry,
    DestinationRuntimeRegistry,
    SourceRuntimeRegistry,
    SyncPairDescriptor,
    SyncPairRegistry,
    validate_adapter_capabilities,
)
from archive_sync_engine.sync.runtime_registry import SyncRuntimeRegistry


def test_default_adapter_capabilities_are_consistent() -> None:
    report = validate_adapter_capabilities()

    assert report.valid
    assert report.errors == ()


def test_source_adapter_without_source_runtime_is_reported() -> None:
    adapters = AdapterRegistry((AdapterDescriptor("example", source=True),))

    report = validate_adapter_capabilities(
        adapters=adapters,
        source_runtimes=SourceRuntimeRegistry(),
        destination_runtimes=DestinationRuntimeRegistry(),
        sync_pairs=SyncPairRegistry(),
        sync_runtimes=SyncRuntimeRegistry(),
    )

    assert report.errors == ("Adapter 'example' is source-enabled but has no source runtime.",)


def test_orphan_runtime_and_pair_are_reported() -> None:
    adapters = AdapterRegistry(
        (
            AdapterDescriptor("source", source=True),
            AdapterDescriptor("destination", destination=True),
        )
    )
    source_runtimes = SourceRuntimeRegistry({"source": lambda request: object()})
    destination_runtimes = DestinationRuntimeRegistry({"destination": lambda request: object()})
    pairs = SyncPairRegistry((SyncPairDescriptor("source", "destination"),))
    runtimes = SyncRuntimeRegistry()

    report = validate_adapter_capabilities(
        adapters=adapters,
        source_runtimes=source_runtimes,
        destination_runtimes=destination_runtimes,
        sync_pairs=pairs,
        sync_runtimes=runtimes,
    )

    assert report.errors == (
        "Sync pair 'source' -> 'destination' has no synchronization runtime.",
    )


def test_runtime_without_supported_pair_is_reported() -> None:
    adapters = AdapterRegistry(
        (
            AdapterDescriptor("source", source=True),
            AdapterDescriptor("destination", destination=True),
        )
    )
    source_runtimes = SourceRuntimeRegistry({"source": lambda request: object()})
    destination_runtimes = DestinationRuntimeRegistry({"destination": lambda request: object()})
    runtimes = SyncRuntimeRegistry({("source", "destination"): lambda request: object()})

    report = validate_adapter_capabilities(
        adapters=adapters,
        source_runtimes=source_runtimes,
        destination_runtimes=destination_runtimes,
        sync_pairs=SyncPairRegistry(),
        sync_runtimes=runtimes,
    )

    assert report.errors == (
        "Synchronization runtime 'source' -> 'destination' has no supported sync pair.",
    )
