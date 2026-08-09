"""Message reply synchronization operations."""
from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.models.ids import MessageId

from .base import SyncOperation


@dataclass(frozen=True, slots=True)
class SetMessageReplyOperation(SyncOperation):
    """Set or clear a message's canonical reply relationship.

    ``reply_to`` is a canonical message identifier. The executor resolves
    both message identifiers to destination references through the
    execution-local reference context.

    ``canonical_fingerprint`` is supplied only when this operation completes
    the complete canonical message baseline.
    """

    message_id: MessageId
    reply_to: MessageId | None
    canonical_fingerprint: str | None = None
