"""Registry for concrete destination adapter runtimes."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .destination_runtime_request import DestinationRuntimeRequest

DestinationRuntimeFactory = Callable[[DestinationRuntimeRequest], Any]
DestinationRuntimeConfigFactory = Callable[[Any, tuple[str, ...], Mapping[str, Any]], Mapping[str, Any]]


class DestinationRuntimeRegistry:
    """Register destination runtimes and their adapter-specific config builders."""

    def __init__(
        self,
        factories: Mapping[str, DestinationRuntimeFactory] | None = None,
        config_factories: Mapping[str, DestinationRuntimeConfigFactory] | None = None,
    ) -> None:
        self._factories: dict[str, DestinationRuntimeFactory] = {}
        self._config_factories: dict[str, DestinationRuntimeConfigFactory] = {}
        if factories:
            for name, factory in factories.items():
                self.register(name, factory)
        if config_factories:
            for name, factory in config_factories.items():
                self.register_config_factory(name, factory)

    @staticmethod
    def _normalize(name: str) -> str:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("Destination adapter name must not be empty.")
        return normalized

    def register(self, name: str, factory: DestinationRuntimeFactory) -> None:
        normalized = self._normalize(name)
        if not callable(factory):
            raise TypeError(f"Destination runtime factory for {normalized!r} must be callable.")
        if normalized in self._factories:
            raise ValueError(f"Destination runtime {normalized!r} is already registered.")
        self._factories[normalized] = factory

    def register_config_factory(self, name: str, factory: DestinationRuntimeConfigFactory) -> None:
        normalized = self._normalize(name)
        if not callable(factory):
            raise TypeError(f"Destination runtime config factory for {normalized!r} must be callable.")
        if normalized in self._config_factories:
            raise ValueError(f"Destination runtime config factory {normalized!r} is already registered.")
        self._config_factories[normalized] = factory

    def resolve(self, name: str) -> DestinationRuntimeFactory:
        normalized = self._normalize(name)
        try:
            return self._factories[normalized]
        except KeyError as exc:
            available = ", ".join(sorted(self._factories)) or "none"
            raise ValueError(
                f"Unknown destination adapter {name!r}. Available destination adapters: {available}."
            ) from exc

    def build_config(
        self,
        name: str,
        credentials: Any,
        scope: tuple[str, ...],
        overrides: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        normalized = self._normalize(name)
        try:
            factory = self._config_factories[normalized]
        except KeyError as exc:
            available = ", ".join(sorted(self._config_factories)) or "none"
            raise ValueError(
                f"No destination runtime configuration factory is registered for {normalized!r}. "
                f"Available: {available}."
            ) from exc
        return factory(credentials, tuple(scope), dict(overrides or {}))

    def create(self, name: str, request: DestinationRuntimeRequest) -> Any:
        normalized = self._normalize(name)
        if request.adapter != normalized:
            raise ValueError(
                "Destination runtime request adapter does not match the requested runtime adapter."
            )
        return self.resolve(normalized)(request)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def list(self) -> tuple[str, ...]:
        return self.names()


def default_destination_runtime_registry(
    fluxer_factory: DestinationRuntimeFactory | None = None,
    fluxer_config_factory: DestinationRuntimeConfigFactory | None = None,
) -> DestinationRuntimeRegistry:
    """Return destination runtimes shipped by the current application."""
    if fluxer_factory is None or fluxer_config_factory is None:
        from archive_sync_engine.adapters.fluxer_runtime import (
            FluxerDestinationRuntime,
            build_fluxer_destination_runtime_config,
        )
        if fluxer_factory is None:
            fluxer_factory = FluxerDestinationRuntime.from_destination_runtime_request
        if fluxer_config_factory is None:
            fluxer_config_factory = build_fluxer_destination_runtime_config
    return DestinationRuntimeRegistry(
        {"fluxer": fluxer_factory},
        {"fluxer": fluxer_config_factory},
    )
