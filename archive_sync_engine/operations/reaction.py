"""
Reaction synchronization operations.

Reaction operations identify both the message being synchronized and the
canonical reaction being added or removed.
"""

from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.models import CanonicalReaction
from archive_sync_engine.models.ids import MessageId
from archive_sync_engine.operations.base import SyncOperation


@dataclass(frozen=True, slots=True)
class AddReactionOperation(SyncOperation):
    """
    Add a reaction to a message.

    resulting_reactions represents the canonical reaction baseline after
    this operation succeeds. canonical_fingerprint is supplied only when
    this operation completes the complete canonical message baseline.
    """

    message_id: MessageId
    reaction: CanonicalReaction
    resulting_reactions: tuple[CanonicalReaction, ...] | None = None
    canonical_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class RemoveReactionOperation(SyncOperation):
    """
    Remove a reaction from a message.

    resulting_reactions represents the canonical reaction baseline after
    this operation succeeds. canonical_fingerprint is supplied only when
    this operation completes the complete canonical message baseline.
    """

    message_id: MessageId
    reaction: CanonicalReaction
    resulting_reactions: tuple[CanonicalReaction, ...] | None = None
    canonical_fingerprint: str | None = None
