"""Adapter-neutral request data used to construct synchronization runtimes."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class SyncRuntimeRequest:
    """Non-secret runtime composition request.

    The request identifies adapters and opaque scopes. Adapter-specific runtime
    configuration is carried as opaque values and interpreted only by the
    concrete runtime factory registered for the adapter pair.
    """

    input_adapter: str
    input_scope: tuple[str, ...]
    destination_adapter: str
    destination_scope: tuple[str, ...]
    archive_path: Path
    adapter_config: Mapping[str, Any]

    def __post_init__(self) -> None:
        input_adapter = self.input_adapter.strip().lower()
        destination_adapter = self.destination_adapter.strip().lower()
        if not input_adapter:
            raise ValueError("Input adapter name must not be empty.")
        if not destination_adapter:
            raise ValueError("Destination adapter name must not be empty.")
        if any(not value.strip() for value in self.input_scope):
            raise ValueError("Input scope values must not be empty.")
        if any(not value.strip() for value in self.destination_scope):
            raise ValueError("Destination scope values must not be empty.")
        object.__setattr__(self, "input_adapter", input_adapter)
        object.__setattr__(self, "destination_adapter", destination_adapter)
        object.__setattr__(self, "archive_path", self.archive_path.expanduser().resolve())
        object.__setattr__(self, "adapter_config", dict(self.adapter_config))
