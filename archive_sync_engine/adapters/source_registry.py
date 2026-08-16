"""Registry for source/input adapter runtimes.

The source-runtime registry is intentionally separate from the generic adapter
role registry.  The generic registry describes which roles an adapter supports;
this registry supplies the concrete runtime factory used to construct a source
runtime for an import workflow.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


SourceRuntimeFactory = Callable[..., Any]


class SourceRuntimeRegistry:
    """Register and resolve concrete source runtime factories by adapter name."""

    def __init__(self, factories: Mapping[str, SourceRuntimeFactory] | None = None) -> None:
        self._factories: dict[str, SourceRuntimeFactory] = {}
        if factories:
            for name, factory in factories.items():
                self.register(name, factory)

    @staticmethod
    def _normalize(name: str) -> str:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("Source adapter name must not be empty.")
        return normalized

    def register(self, name: str, factory: SourceRuntimeFactory) -> None:
        """Register a source runtime factory, rejecting duplicate names."""
        normalized = self._normalize(name)
        if not callable(factory):
            raise TypeError(f"Source runtime factory for {normalized!r} must be callable.")
        if normalized in self._factories:
            raise ValueError(f"Source runtime {normalized!r} is already registered.")
        self._factories[normalized] = factory

    def resolve(self, name: str) -> SourceRuntimeFactory:
        """Return the factory registered for a source adapter."""
        normalized = self._normalize(name)
        try:
            return self._factories[normalized]
        except KeyError as exc:
            available = ", ".join(sorted(self._factories)) or "none"
            raise ValueError(
                f"Unknown source adapter {name!r}. Available source adapters: {available}."
            ) from exc

    def create(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Construct a source runtime using the registered factory."""
        return self.resolve(name)(*args, **kwargs)

    def names(self) -> tuple[str, ...]:
        """Return registered source adapter names in stable order."""
        return tuple(sorted(self._factories))

    def list(self) -> tuple[str, ...]:
        """Alias for ``names`` for callers that enumerate registry entries."""
        return self.names()


def default_source_runtime_registry() -> SourceRuntimeRegistry:
    """Return the source runtimes shipped by the current application."""
    from archive_sync_engine.adapters.discord.runtime import DiscordSourceRuntime

    # The factory is deliberately registered as a class rather than being
    # instantiated here, keeping client construction and credentials in the
    # selected source runtime boundary.
    return SourceRuntimeRegistry({"discord": DiscordSourceRuntime})
