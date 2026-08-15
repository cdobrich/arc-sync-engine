"""Persisted, non-secret configuration for an Archive run."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class RunDirection(str, Enum):
    """Direction represented by a persisted run configuration."""

    IMPORT = "import"
    SYNC = "sync"


@dataclass(frozen=True, slots=True)
class SyncRunConfiguration:
    """Non-secret configuration needed to identify and resume a run.

    Source-platform details are deliberately represented by the selected
    adapter name and opaque scope values. The persistence layer therefore
    does not acquire knowledge of Discord, Fluxer, or future adapters.
    Authentication credentials are never persisted here.
    """

    direction: RunDirection
    input_adapter: str
    input_scope: tuple[str, ...] = ()
    destination_adapter: str | None = None
    destination_scope: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        adapter = self.input_adapter.strip().lower()
        if not adapter:
            raise ValueError("Input adapter name must not be empty.")
        object.__setattr__(self, "input_adapter", adapter)

        if any(not value.strip() for value in self.input_scope):
            raise ValueError("Input scope values must not be empty.")
        if self.destination_adapter is not None:
            destination = self.destination_adapter.strip().lower()
            if not destination:
                raise ValueError("Destination adapter name must not be empty.")
            object.__setattr__(self, "destination_adapter", destination)
        if any(not value.strip() for value in self.destination_scope):
            raise ValueError("Destination scope values must not be empty.")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "direction": self.direction.value,
            "input_adapter": self.input_adapter,
            "input_scope": list(self.input_scope),
            "destination_adapter": self.destination_adapter,
            "destination_scope": list(self.destination_scope),
        }

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> "SyncRunConfiguration":
        if not isinstance(data, Mapping):
            raise ValueError("Run configuration must contain a JSON object.")

        raw_input_scope = data.get("input_scope", [])
        if not isinstance(raw_input_scope, list):
            raise ValueError("Run configuration input_scope must be a JSON array.")
        raw_destination_scope = data.get("destination_scope", [])
        if not isinstance(raw_destination_scope, list):
            raise ValueError(
                "Run configuration destination_scope must be a JSON array."
            )

        direction = RunDirection(str(data["direction"]))
        destination = data.get("destination_adapter")
        return cls(
            direction=direction,
            input_adapter=str(data["input_adapter"]),
            input_scope=tuple(str(value) for value in raw_input_scope),
            destination_adapter=(str(destination) if destination is not None else None),
            destination_scope=tuple(str(value) for value in raw_destination_scope),
        )
