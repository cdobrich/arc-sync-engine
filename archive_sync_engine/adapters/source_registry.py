"""Registry for source-platform import runtimes.

The import application workflow depends on this registry rather than on a
specific platform. Concrete adapters register their runtime factory under a
stable adapter name. The registry deliberately contains no platform-specific
credential or import logic.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .source_runtime import SourceImportRuntime

SourceRuntimeFactory = Callable[[Any], SourceImportRuntime]


class SourceRuntimeRegistry:
    """Resolve source runtime factories by adapter name."""

    def __init__(self) -> None:
        self._factories: dict[str, SourceRuntimeFactory] = {}

    def register(self, name: str, factory: SourceRuntimeFactory) -> None:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("Source adapter name must not be empty.")
        if normalized in self._factories:
            raise ValueError(f"Source adapter '{normalized}' is already registered.")
        self._factories[normalized] = factory

    def resolve(self, name: str) -> SourceRuntimeFactory:
        normalized = name.strip().lower()
        try:
            return self._factories[normalized]
        except KeyError as exc:
            available = ", ".join(sorted(self._factories)) or "none"
            raise ValueError(
                f"Unknown source adapter '{name}'. Available adapters: {available}."
            ) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))
