"""Validation of registered adapter roles and concrete runtime capabilities."""
from __future__ import annotations

from dataclasses import dataclass

from .destination_registry import default_destination_runtime_registry
from .registry import AdapterRegistry, default_adapter_registry
from .source_registry import default_source_runtime_registry
from .sync_registry import SyncPairRegistry, default_sync_pair_registry
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from archive_sync_engine.sync.runtime_registry import SyncRuntimeRegistry


@dataclass(frozen=True, slots=True)
class AdapterCapabilityReport:
    """Read-only consistency report for adapter/runtime registration."""

    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors


def validate_adapter_capabilities(
    *,
    adapters: AdapterRegistry | None = None,
    source_runtimes=None,
    destination_runtimes=None,
    sync_pairs: SyncPairRegistry | None = None,
    sync_runtimes: SyncRuntimeRegistry | None = None,
) -> AdapterCapabilityReport:
    """Validate consistency across adapter roles and concrete runtimes.

    This performs registration-only checks. It does not instantiate runtimes,
    resolve credentials, contact external services, or modify an Archive.
    """
    adapters = adapters or default_adapter_registry()
    source_runtimes = source_runtimes or default_source_runtime_registry()
    destination_runtimes = destination_runtimes or default_destination_runtime_registry()
    sync_pairs = sync_pairs or default_sync_pair_registry()
    if sync_runtimes is None:
        from archive_sync_engine.sync.runtime_registry import default_sync_runtime_registry

        sync_runtimes = default_sync_runtime_registry()

    errors: list[str] = []
    descriptors = {descriptor.name: descriptor for descriptor in adapters.list()}
    source_names = set(source_runtimes.list())
    destination_names = set(destination_runtimes.list())
    pair_keys = {pair.key for pair in sync_pairs.list()}
    runtime_keys = set(sync_runtimes.list())

    for name, descriptor in descriptors.items():
        if descriptor.source and name not in source_names:
            errors.append(f"Adapter {name!r} is source-enabled but has no source runtime.")
        if descriptor.destination and name not in destination_names:
            errors.append(
                f"Adapter {name!r} is destination-enabled but has no destination runtime."
            )

    for name in sorted(source_names):
        descriptor = descriptors.get(name)
        if descriptor is None:
            errors.append(f"Source runtime {name!r} has no registered adapter descriptor.")
        elif not descriptor.source:
            errors.append(f"Source runtime {name!r} is registered for a non-source adapter.")

    for name in sorted(destination_names):
        descriptor = descriptors.get(name)
        if descriptor is None:
            errors.append(
                f"Destination runtime {name!r} has no registered adapter descriptor."
            )
        elif not descriptor.destination:
            errors.append(
                f"Destination runtime {name!r} is registered for a non-destination adapter."
            )

    for source, destination in sorted(pair_keys):
        source_descriptor = descriptors.get(source)
        destination_descriptor = descriptors.get(destination)
        if source_descriptor is None:
            errors.append(f"Sync pair {source!r} -> {destination!r} has no source adapter descriptor.")
        elif not source_descriptor.source:
            errors.append(f"Sync pair {source!r} -> {destination!r} uses a non-source adapter.")
        if destination_descriptor is None:
            errors.append(
                f"Sync pair {source!r} -> {destination!r} has no destination adapter descriptor."
            )
        elif not destination_descriptor.destination:
            errors.append(
                f"Sync pair {source!r} -> {destination!r} uses a non-destination adapter."
            )
        if (source, destination) not in runtime_keys:
            errors.append(
                f"Sync pair {source!r} -> {destination!r} has no synchronization runtime."
            )

    for source, destination in sorted(runtime_keys):
        if (source, destination) not in pair_keys:
            errors.append(
                f"Synchronization runtime {source!r} -> {destination!r} has no supported sync pair."
            )

    return AdapterCapabilityReport(tuple(errors))
