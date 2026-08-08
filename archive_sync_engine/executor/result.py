"""
Synchronization execution results.
"""

from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """
    Result of executing a single SyncOperation.

    canonical_id identifies the canonical entity affected by the
    operation.

    Destination references are populated when execution creates or
    establishes a corresponding destination object.

    canonical_fingerprint records the canonical state successfully
    represented by the destination after the operation.

    deleted indicates that the operation successfully removed the
    corresponding destination object.
    """

    canonical_id: str | None = None

    canonical_fingerprint: str | None = None

    deleted: bool = False

    conversation: DestinationConversationRef | None = None
    identity: DestinationIdentityRef | None = None
    message: DestinationMessageRef | None = None