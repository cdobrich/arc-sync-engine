"""Validate consistency between adapter roles and concrete runtimes."""
from __future__ import annotations

from dataclasses import dataclass

from .destination_registry import default_destination_runtime_registry
from .registry import default_adapter_registry
from .source_registry import default_source_runtime_registry
from .sync_registry import default_sync_pair_registry


def default_sync_runtime_registry():
    """Lazily resolve the synchronization runtime registry.

    Keeping this import behind a function boundary prevents importing the
    adapters package from eagerly initializing the synchronization subsystem,
    whose executor depends on adapter interfaces. The indirection also keeps
    this dependency patchable for capability-validation tests.
    """
    from archive_sync_engine.sync.runtime_registry import (
        default_sync_runtime_registry as _default_sync_runtime_registry,
    )

    return _default_sync_runtime_registry()


@dataclass(frozen=True, slots=True)
class AdapterCapabilityReport:
    """Result of validating registered adapter/runtime capabilities."""

    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors


def validate_adapter_capabilities() -> AdapterCapabilityReport:
    """Ensure role, runtime, pair, and synchronization registrations agree."""
    adapters = default_adapter_registry().list()
    sources = set(default_source_runtime_registry().names())
    destinations = set(default_destination_runtime_registry().names())
    pairs = {pair.key for pair in default_sync_pair_registry().list()}
    runtimes = set(default_sync_runtime_registry().keys())
    errors: list[str] = []

    for descriptor in adapters:
        if descriptor.source and descriptor.name not in sources:
            errors.append(
                f"Adapter {descriptor.name!r} supports source/import use but has no source runtime."
            )
        if descriptor.destination and descriptor.name not in destinations:
            errors.append(
                f"Adapter {descriptor.name!r} supports destination use but has no destination runtime."
            )

    adapter_names = {descriptor.name for descriptor in adapters}
    for name in sorted(sources):
        if name not in adapter_names:
            errors.append(f"Source runtime {name!r} has no registered adapter descriptor.")
    for name in sorted(destinations):
        if name not in adapter_names:
            errors.append(f"Destination runtime {name!r} has no registered adapter descriptor.")

    for source, destination in sorted(pairs):
        if (source, destination) not in runtimes:
            errors.append(
                f"Supported sync pair {source!r} -> {destination!r} has no synchronization runtime."
            )
    for source, destination in sorted(runtimes):
        if (source, destination) not in pairs:
            errors.append(
                f"Synchronization runtime {source!r} -> {destination!r} has no supported sync pair."
            )

    return AdapterCapabilityReport(tuple(errors))
