"""Registry for concrete source/input adapter runtimes."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .source_runtime_request import SourceRuntimeRequest

SourceRuntimeFactory = Callable[[SourceRuntimeRequest], Any]
SourceRuntimeConfigFactory = Callable[[Any, tuple[str, ...], Mapping[str, Any]], Any]


class SourceRuntimeRegistry:
    """Register source runtimes and their adapter-specific config builders."""

    def __init__(
        self,
        factories: Mapping[str, SourceRuntimeFactory] | None = None,
        config_factories: Mapping[str, SourceRuntimeConfigFactory] | None = None,
    ) -> None:
        self._factories: dict[str, SourceRuntimeFactory] = {}
        self._config_factories: dict[str, SourceRuntimeConfigFactory] = {}
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
            raise ValueError("Source adapter name must not be empty.")
        return normalized

    def register(self, name: str, factory: SourceRuntimeFactory) -> None:
        normalized = self._normalize(name)
        if not callable(factory):
            raise TypeError(f"Source runtime factory for {normalized!r} must be callable.")
        if normalized in self._factories:
            raise ValueError(f"Source runtime {normalized!r} is already registered.")
        self._factories[normalized] = factory

    def register_config_factory(self, name: str, factory: SourceRuntimeConfigFactory) -> None:
        normalized = self._normalize(name)
        if not callable(factory):
            raise TypeError(f"Source runtime config factory for {normalized!r} must be callable.")
        if normalized in self._config_factories:
            raise ValueError(f"Source runtime config factory {normalized!r} is already registered.")
        self._config_factories[normalized] = factory

    def resolve(self, name: str) -> SourceRuntimeFactory:
        normalized = self._normalize(name)
        try:
            return self._factories[normalized]
        except KeyError as exc:
            available = ", ".join(sorted(self._factories)) or "none"
            raise ValueError(
                f"Unknown source adapter {name!r}. Available source adapters: {available}."
            ) from exc

    def build_config(
        self,
        name: str,
        credentials: Any,
        scope: tuple[str, ...],
        overrides: Mapping[str, Any] | None = None,
    ) -> Any:
        normalized = self._normalize(name)
        try:
            factory = self._config_factories[normalized]
        except KeyError as exc:
            available = ", ".join(sorted(self._config_factories)) or "none"
            raise ValueError(
                f"No source runtime configuration factory is registered for {normalized!r}. "
                f"Available: {available}."
            ) from exc
        return factory(credentials, tuple(scope), dict(overrides or {}))

    def create(self, name: str, request: SourceRuntimeRequest) -> Any:
        normalized = self._normalize(name)
        if request.adapter != normalized:
            raise ValueError(
                "Source runtime request adapter does not match the requested runtime adapter."
            )
        return self.resolve(normalized)(request)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def list(self) -> tuple[str, ...]:
        return self.names()


def default_source_runtime_registry(
    discord_factory: SourceRuntimeFactory | None = None,
    discord_config_factory: SourceRuntimeConfigFactory | None = None,
    fluxer_factory: SourceRuntimeFactory | None = None,
    fluxer_config_factory: SourceRuntimeConfigFactory | None = None,
) -> SourceRuntimeRegistry:
    """Return source runtimes shipped by the current application."""
    if discord_factory is None or discord_config_factory is None:
        from archive_sync_engine.adapters.discord.runtime import (
            DiscordSourceRuntime,
            build_discord_source_runtime_config,
        )
        if discord_factory is None:
            discord_factory = DiscordSourceRuntime.from_source_runtime_request
        if discord_config_factory is None:
            discord_config_factory = build_discord_source_runtime_config
    if fluxer_factory is None or fluxer_config_factory is None:
        from archive_sync_engine.adapters.fluxer_source_runtime import (
            FluxerSourceRuntime,
            build_fluxer_source_runtime_config,
        )
        if fluxer_factory is None:
            fluxer_factory = FluxerSourceRuntime.from_source_runtime_request
        if fluxer_config_factory is None:
            fluxer_config_factory = build_fluxer_source_runtime_config
    return SourceRuntimeRegistry(
        {"discord": discord_factory, "fluxer": fluxer_factory},
        {"discord": discord_config_factory, "fluxer": fluxer_config_factory},
    )
