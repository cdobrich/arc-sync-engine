"""Adapter-neutral request data for constructing destination runtimes."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class DestinationRuntimeRequest:
    """Non-secret request used to construct one destination runtime.

    Destination-specific configuration is intentionally opaque. The concrete
    destination runtime factory is responsible for interpreting it.
    """

    adapter: str
    scope: tuple[str, ...]
    archive_path: Path
    adapter_config: Mapping[str, Any]

    def __post_init__(self) -> None:
        adapter = self.adapter.strip().lower()
        if not adapter:
            raise ValueError("Destination adapter name must not be empty.")
        if any(not value.strip() for value in self.scope):
            raise ValueError("Destination scope values must not be empty.")
        object.__setattr__(self, "adapter", adapter)
        object.__setattr__(self, "archive_path", self.archive_path.expanduser().resolve())
        object.__setattr__(self, "adapter_config", dict(self.adapter_config))
