"""Registry for concrete synchronization runtime factories."""
from __future__ import annotations
from collections.abc import Callable, Mapping
from typing import Any

from .runtime_request import SyncRuntimeRequest

SyncRuntimeFactory = Callable[[SyncRuntimeRequest], Any]
SyncRuntimeKey = tuple[str, str]

class SyncRuntimeRegistry:
    """Register and resolve concrete runtime factories by adapter pair."""
    def __init__(self, factories: Mapping[SyncRuntimeKey, SyncRuntimeFactory] | None = None) -> None:
        self._factories: dict[SyncRuntimeKey, SyncRuntimeFactory] = {}
        if factories:
            for (source, destination), factory in factories.items():
                self.register(source, destination, factory)

    @staticmethod
    def _normalize(name: str) -> str:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("Sync runtime adapter name must not be empty.")
        return normalized

    @classmethod
    def _key(cls, source: str, destination: str) -> SyncRuntimeKey:
        return cls._normalize(source), cls._normalize(destination)

    def register(self, source: str, destination: str, factory: SyncRuntimeFactory) -> None:
        key = self._key(source, destination)
        if not callable(factory):
            raise TypeError(f"Sync runtime factory for {key[0]!r} -> {key[1]!r} must be callable.")
        if key in self._factories:
            raise ValueError(f"Sync runtime for {key[0]!r} -> {key[1]!r} is already registered.")
        self._factories[key] = factory

    def resolve(self, source: str, destination: str) -> SyncRuntimeFactory:
        key = self._key(source, destination)
        try:
            return self._factories[key]
        except KeyError as exc:
            available = ", ".join(f"{left}->{right}" for left, right in sorted(self._factories)) or "none"
            raise ValueError(
                f"No synchronization runtime is registered for {source!r} -> {destination!r}. "
                f"Available runtimes: {available}."
            ) from exc

    def create(self, source: str, destination: str, request: SyncRuntimeRequest) -> Any:
        """Construct a runtime for an adapter pair from an adapter-neutral request."""
        if request.input_adapter != self._normalize(source) or request.destination_adapter != self._normalize(destination):
            raise ValueError("Sync runtime request adapter pair does not match the requested runtime pair.")
        return self.resolve(source, destination)(request)

    def keys(self) -> tuple[SyncRuntimeKey, ...]:
        return tuple(sorted(self._factories))

    def list(self) -> tuple[SyncRuntimeKey, ...]:
        return self.keys()


def default_sync_runtime_registry(
    discord_fluxer_factory: SyncRuntimeFactory | None = None,
) -> SyncRuntimeRegistry:
    """Return runtime factories shipped by the current application."""
    if discord_fluxer_factory is None:
        from archive_sync_engine.sync.discord_fluxer_runtime import DiscordFluxerSyncRuntime
        discord_fluxer_factory = DiscordFluxerSyncRuntime.from_runtime_request
    return SyncRuntimeRegistry({("discord", "fluxer"): discord_fluxer_factory})
