"""
Runtime state for a synchronization session.

A SyncSession represents one resumable synchronization operation.

A session may represent either:

    * import from a source endpoint into an Archive Package; or
    * export from an Archive Package to a destination endpoint.

The session is operational state. It is distinct from canonical archive
content and from CanonicalProvenance, which records durable historical
events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from archive_sync_engine.models._validation import (
    require_timezone_aware,
)

class SyncDirection(str, Enum):
    """
    Direction of a synchronization session.
    """

    IMPORT = "import"
    EXPORT = "export"


@dataclass(slots=True)
class SyncSession:
    """
    Runtime state for a resumable synchronization session.

    IMPORT means data is being read from a source endpoint and persisted
    into an Archive Package.

    EXPORT means canonical data is being read from an Archive Package
    and reproduced on a destination endpoint.
    """

    id: str

    direction: SyncDirection

    started_at: datetime

    updated_at: datetime

    paused: bool = False

    completed: bool = False

    cancelled: bool = False

    error: str | None = None

    checkpoint: str | None = None

    def __post_init__(self) -> None:
        """
        Validate basic session invariants.
        """

        if not self.id:
            raise ValueError(
                "id cannot be empty."
            )

        require_timezone_aware(
            "started_at",
            self.started_at,
        )

        require_timezone_aware(
            "updated_at",
            self.updated_at,
        )

        if self.updated_at < self.started_at:
            raise ValueError(
                "updated_at cannot precede started_at."
            )

        if self.paused and self.completed:
            raise ValueError(
                "A completed session cannot be paused."
            )

        if self.paused and self.cancelled:
            raise ValueError(
                "A cancelled session cannot be paused."
            )

        if self.completed and self.cancelled:
            raise ValueError(
                "A session cannot be both completed and cancelled."
            )

    def pause(
        self,
    ) -> None:
        """
        Pause the current synchronization session.

        A completed or cancelled session cannot be paused.
        """

        if self.completed:
            raise RuntimeError(
                "A completed session cannot be paused."
            )

        if self.cancelled:
            raise RuntimeError(
                "A cancelled session cannot be paused."
            )

        self.paused = True
        self._touch()

    def resume(
        self,
    ) -> None:
        """
        Resume a paused synchronization session.

        Resuming a session does not alter its checkpoint. The checkpoint
        remains the durable boundary from which synchronization resumes.
        """

        if self.completed:
            raise RuntimeError(
                "A completed session cannot be resumed."
            )

        if self.cancelled:
            raise RuntimeError(
                "A cancelled session cannot be resumed."
            )

        if not self.paused:
            raise RuntimeError(
                "A session that is not paused cannot be resumed."
            )

        self.paused = False
        self._touch()

    def complete(
        self,
    ) -> None:
        """
        Mark the synchronization session as successfully completed.
        """

        if self.cancelled:
            raise RuntimeError(
                "A cancelled session cannot be completed."
            )

        if self.paused:
            raise RuntimeError(
                "A paused session cannot be completed."
            )

        self.completed = True
        self._touch()

    def cancel(
        self,
    ) -> None:
        """
        Mark the synchronization session as cancelled.
        """

        if self.completed:
            raise RuntimeError(
                "A completed session cannot be cancelled."
            )

        self.cancelled = True
        self.paused = False
        self._touch()

    def fail(
        self,
        error: str,
    ) -> None:
        """
        Mark the synchronization session as failed.

        Failure preserves the checkpoint already reached. The session is
        not considered completed or cancelled, allowing the caller to
        inspect the error and decide whether to resume or abandon it.
        """

        if self.completed:
            raise RuntimeError(
                "A completed session cannot fail."
            )

        if self.cancelled:
            raise RuntimeError(
                "A cancelled session cannot fail."
            )

        if not error:
            raise ValueError(
                "error cannot be empty."
            )

        self.error = error
        self.paused = False
        self._touch()

    def advance_checkpoint(
        self,
        value: str,
    ) -> None:
        """
        Advance the synchronization checkpoint.

        The checkpoint represents the last successfully persisted
        synchronization boundary. It must never be advanced merely because
        an operation was attempted.
        """

        if self.completed:
            raise RuntimeError(
                "A completed session cannot advance its checkpoint."
            )

        if self.cancelled:
            raise RuntimeError(
                "A cancelled session cannot advance its checkpoint."
            )

        if not value:
            raise ValueError(
                "checkpoint cannot be empty."
            )

        self.checkpoint = value
        self.error = None
        self._touch()

    def _touch(
        self,
    ) -> None:
        """
        Update the session modification timestamp.
        """

        self.updated_at = datetime.now(
            timezone.utc,
        )

    #
    # JSON
    #

    def to_json_dict(
        self,
    ) -> dict[str, object]:
        """
        Convert the synchronization session into a JSON-compatible
        dictionary.
        """

        return {
            "id": self.id,
            "direction": self.direction.value,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "paused": self.paused,
            "completed": self.completed,
            "cancelled": self.cancelled,
            "error": self.error,
            "checkpoint": self.checkpoint,
        }

    @classmethod
    def from_json_dict(
        cls,
        data: dict[str, Any],
    ) -> "SyncSession":
        """
        Reconstruct a synchronization session from a JSON-compatible
        dictionary.
        """

        return cls(
            id=str(data["id"]),
            direction=SyncDirection(
                str(data["direction"]),
            ),
            started_at=datetime.fromisoformat(
                str(data["started_at"]),
            ),
            updated_at=datetime.fromisoformat(
                str(data["updated_at"]),
            ),
            paused=bool(
                data.get(
                    "paused",
                    False,
                ),
            ),
            completed=bool(
                data.get(
                    "completed",
                    False,
                ),
            ),
            cancelled=bool(
                data.get(
                    "cancelled",
                    False,
                ),
            ),
            error=(
                str(data["error"])
                if data.get("error") is not None
                else None
            ),
            checkpoint=(
                str(data["checkpoint"])
                if data.get("checkpoint") is not None
                else None
            ),
        )
