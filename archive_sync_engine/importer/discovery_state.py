"""Durable discovery-phase checkpoint state for canonical imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


class DiscoveryPhase(str, Enum):
    """Durable lifecycle phases of source discovery."""

    IDENTITIES = "identities"
    CANONICAL = "canonical"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class DiscoveryState:
    """Persistent boundary for the source-discovery portion of an import.

    The state deliberately contains only adapter-neutral lifecycle metadata.
    Adapter-specific traversal cursors can be added by later slices without
    changing the coordinator's transaction/checkpoint contract.
    """

    phase: DiscoveryPhase
    batch_number: int = 0
    records_committed: int = 0
    last_record_key: str | None = None
    updated_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.batch_number < 0:
            raise ValueError("Discovery batch number cannot be negative.")
        if self.records_committed < 0:
            raise ValueError("Discovery committed record count cannot be negative.")
        if self.updated_at is not None and (
            self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None
        ):
            raise ValueError("Discovery timestamps must be timezone-aware.")

    @classmethod
    def identities_started(cls) -> "DiscoveryState":
        return cls(
            phase=DiscoveryPhase.IDENTITIES,
            updated_at=datetime.now(timezone.utc),
        )

    def advance_batch(
        self,
        *,
        records_committed: int,
        last_record_key: str | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "DiscoveryState":
        if records_committed < self.records_committed:
            raise ValueError("Discovery record count cannot move backwards.")
        return DiscoveryState(
            phase=self.phase,
            batch_number=self.batch_number + 1,
            records_committed=records_committed,
            last_record_key=last_record_key,
            updated_at=datetime.now(timezone.utc),
            metadata=dict(self.metadata if metadata is None else metadata),
        )

    def with_phase(self, phase: DiscoveryPhase) -> "DiscoveryState":
        return DiscoveryState(
            phase=phase,
            batch_number=self.batch_number,
            records_committed=self.records_committed,
            last_record_key=self.last_record_key,
            updated_at=datetime.now(timezone.utc),
            metadata=dict(self.metadata),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "batch_number": self.batch_number,
            "records_committed": self.records_committed,
            "last_record_key": self.last_record_key,
            "updated_at": (
                self.updated_at.astimezone(timezone.utc).isoformat()
                if self.updated_at is not None
                else None
            ),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_json_dict(cls, data: Any) -> "DiscoveryState":
        if not isinstance(data, dict):
            raise ValueError("Discovery state must contain a JSON object.")
        raw_updated_at = data.get("updated_at")
        updated_at = (
            datetime.fromisoformat(str(raw_updated_at))
            if raw_updated_at is not None
            else None
        )
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("Discovery state metadata must contain a JSON object.")
        return cls(
            phase=DiscoveryPhase(str(data["phase"])),
            batch_number=int(data.get("batch_number", 0)),
            records_committed=int(data.get("records_committed", 0)),
            last_record_key=(
                str(data["last_record_key"])
                if data.get("last_record_key") is not None
                else None
            ),
            updated_at=updated_at,
            metadata=metadata,
        )
