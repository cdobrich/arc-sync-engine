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

    The coordinator uses this information to update persistent synchronization metadata.
    """

    conversation: DestinationConversationRef | None = None

    identity: DestinationIdentityRef | None = None

    message: DestinationMessageRef | None = None
