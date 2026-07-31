"""
Reaction synchronization operations.

Reaction operations identify both the message being synchronized and the
canonical reaction being added or removed.

CanonicalReaction intentionally does not contain a message identifier because
the archive stores the message/reaction relationship separately. The
synchronization operation must therefore carry that relationship explicitly.
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
    """

    message_id: MessageId
    reaction: CanonicalReaction


@dataclass(frozen=True, slots=True)
class RemoveReactionOperation(SyncOperation):
    """
    Remove a reaction from a message.
    """

    message_id: MessageId
    reaction: CanonicalReaction