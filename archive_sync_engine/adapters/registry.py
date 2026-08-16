"""Registry for platform adapter identities and supported roles.

The registry is deliberately independent of concrete client construction. It
records which adapter names are available for source and/or destination use,
so CLI workflows can validate adapter selections without embedding platform
conditionals in generic orchestration code.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AdapterDescriptor:
    """Describes one platform adapter and the roles it currently supports."""

    name: str
    source: bool = False
    destination: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        name = self.name.strip().lower()
        if not name:
            raise ValueError("Adapter name must not be empty.")
        if not self.source and not self.destination:
            raise ValueError("An adapter must support source or destination use.")
        object.__setattr__(self, "name", name)


class AdapterRegistry:
    """Explicit registry of adapters known to the current application."""

    def __init__(self, descriptors: tuple[AdapterDescriptor, ...] = ()) -> None:
        self._descriptors: dict[str, AdapterDescriptor] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(self, descriptor: AdapterDescriptor) -> None:
        """Register an adapter descriptor, rejecting duplicate names."""
        if descriptor.name in self._descriptors:
            raise ValueError(f"Adapter {descriptor.name!r} is already registered.")
        self._descriptors[descriptor.name] = descriptor

    def get(self, name: str) -> AdapterDescriptor:
        """Return an adapter descriptor by normalized name."""
        normalized = name.strip().lower()
        try:
            return self._descriptors[normalized]
        except KeyError as exc:
            available = ", ".join(sorted(self._descriptors)) or "none"
            raise ValueError(
                f"Unknown adapter {name!r}. Available adapters: {available}."
            ) from exc

    def require_source(self, name: str) -> AdapterDescriptor:
        descriptor = self.get(name)
        if not descriptor.source:
            raise ValueError(f"Adapter {descriptor.name!r} does not support source/import use.")
        return descriptor

    def require_destination(self, name: str) -> AdapterDescriptor:
        descriptor = self.get(name)
        if not descriptor.destination:
            raise ValueError(
                f"Adapter {descriptor.name!r} does not support destination/sync use."
            )
        return descriptor

    def list(self) -> tuple[AdapterDescriptor, ...]:
        return tuple(self._descriptors[name] for name in sorted(self._descriptors))


def default_adapter_registry() -> AdapterRegistry:
    """Return descriptors for adapters shipped by the current application.

    This describes roles, not client factories. Future adapters can be added
    by registering another descriptor without changing generic CLI workflows.
    """
    return AdapterRegistry(
        (
            AdapterDescriptor(
                name="discord",
                source=True,
                description="Discord source/import adapter.",
            ),
            AdapterDescriptor(
                name="fluxer",
                destination=True,
                description="Fluxer destination/synchronization adapter.",
            ),
        )
    )
