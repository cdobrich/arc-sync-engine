"""Registry for concrete source/input adapter runtimes."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .source_runtime_request import SourceRuntimeRequest

SourceRuntimeFactory = Callable[[SourceRuntimeRequest], Any]


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

    def create(self, name: str, request: SourceRuntimeRequest) -> Any:
        """Construct a source runtime from an adapter-neutral request."""
        normalized = self._normalize(name)
        if request.adapter != normalized:
            raise ValueError(
                "Source runtime request adapter does not match the requested runtime adapter."
            )
        return self.resolve(normalized)(request)

    def names(self) -> tuple[str, ...]:
        """Return registered source adapter names in stable order."""
        return tuple(sorted(self._factories))

    def list(self) -> tuple[str, ...]:
        return self.names()


def default_source_runtime_registry(
    discord_factory: SourceRuntimeFactory | None = None,
) -> SourceRuntimeRegistry:
    """Return source runtimes shipped by the current application."""
    if discord_factory is None:
        from archive_sync_engine.adapters.discord.runtime import DiscordSourceRuntime

        discord_factory = DiscordSourceRuntime.from_source_runtime_request
    return SourceRuntimeRegistry({"discord": discord_factory})
