from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ._validation import require_timezone_aware


@dataclass(frozen=True, slots=True)
class CanonicalEndpoint:
    """
    Identifies an external system involved with an archive.

    Examples:

        Discord server
        Fluxer server
        Slack workspace
    """

    adapter: str
    identifier: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalTransfer:
    """
    Records a single import/export operation.
    """

    source: CanonicalEndpoint
    destination: CanonicalEndpoint | None

    started_at: datetime
    finished_at: datetime | None = None

    imported_messages: int = 0
    exported_messages: int = 0

    def __post_init__(self) -> None:

        require_timezone_aware(
            "started_at",
            self.started_at,
        )

        if self.finished_at is not None:

            require_timezone_aware(
                "finished_at",
                self.finished_at,
            )

            if self.finished_at < self.started_at:

                raise ValueError(
                    "finished_at cannot precede started_at."
                )

        if self.imported_messages < 0:

            raise ValueError(
                "imported_messages cannot be negative."
            )

        if self.exported_messages < 0:

            raise ValueError(
                "exported_messages cannot be negative."
            )


@dataclass(frozen=True, slots=True)
class CanonicalProvenance:
    """
    Historical record describing how an archive was produced and later used.
    """

    history: tuple[
        CanonicalTransfer,
        ...
    ] = field(
        default_factory=tuple,
    )