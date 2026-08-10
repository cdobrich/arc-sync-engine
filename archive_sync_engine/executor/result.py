"""
Synchronization execution results.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)
from archive_sync_engine.models import CanonicalAttachment, CanonicalReaction


class DeletedEntityType(str, Enum):
    """
    Canonical entity type removed by a successful delete operation.
    """

    CONVERSATION = "conversation"
    MESSAGE = "message"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """
    Result of executing a single SyncOperation.

    canonical_fingerprint records complete canonical state only when the
    operation has successfully established that complete state. Message
    component fields allow content, reactions, and pin state to be updated
    independently while a multi-operation message reconciliation is in
    progress.
    """

    canonical_id: str | None = None

    canonical_fingerprint: str | None = None

    message_content_fingerprint: str | None = None

    message_reactions: tuple[CanonicalReaction, ...] | None = None

    message_attachments: tuple[CanonicalAttachment, ...] | None = None

    message_pinned: bool | None = None

    deleted: bool = False

    deleted_entity: DeletedEntityType | None = None

    conversation_parent_id: str | None = None

    conversation: DestinationConversationRef | None = None
    identity: DestinationIdentityRef | None = None
    message: DestinationMessageRef | None = None
