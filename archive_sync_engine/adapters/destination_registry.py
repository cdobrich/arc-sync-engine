"""Registry for concrete destination adapter runtimes."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .destination_runtime_request import DestinationRuntimeRequest

DestinationRuntimeFactory = Callable[[DestinationRuntimeRequest], Any]


class DestinationRuntimeRegistry:
    """Register and resolve concrete destination runtime factories by adapter name."""

    def __init__(
        self,
        factories: Mapping[str, DestinationRuntimeFactory] | None = None,
    ) -> None:
        self._factories: dict[str, DestinationRuntimeFactory] = {}
        if factories:
            for name, factory in factories.items():
                self.register(name, factory)

    @staticmethod
    def _normalize(name: str) -> str:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("Destination adapter name must not be empty.")
        return normalized

    def register(self, name: str, factory: DestinationRuntimeFactory) -> None:
        normalized = self._normalize(name)
        if not callable(factory):
            raise TypeError(
                f"Destination runtime factory for {normalized!r} must be callable."
            )
        if normalized in self._factories:
            raise ValueError(
                f"Destination runtime {normalized!r} is already registered."
            )
        self._factories[normalized] = factory

    def resolve(self, name: str) -> DestinationRuntimeFactory:
        normalized = self._normalize(name)
        try:
            return self._factories[normalized]
        except KeyError as exc:
            available = ", ".join(sorted(self._factories)) or "none"
            raise ValueError(
                f"Unknown destination adapter {name!r}. "
                f"Available destination adapters: {available}."
            ) from exc

    def create(self, name: str, request: DestinationRuntimeRequest) -> Any:
        normalized = self._normalize(name)
        if request.adapter != normalized:
            raise ValueError(
                "Destination runtime request adapter does not match "
                "the requested runtime adapter."
            )
        return self.resolve(normalized)(request)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def list(self) -> tuple[str, ...]:
        return self.names()


def default_destination_runtime_registry(
    fluxer_factory: DestinationRuntimeFactory | None = None,
) -> DestinationRuntimeRegistry:
    """Return destination runtimes shipped by the current application."""
    if fluxer_factory is None:
        from archive_sync_engine.adapters.fluxer_runtime import FluxerDestinationRuntime

        fluxer_factory = FluxerDestinationRuntime.from_destination_runtime_request
    return DestinationRuntimeRegistry({"fluxer": fluxer_factory})
