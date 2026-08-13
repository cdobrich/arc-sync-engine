"""
Message synchronization operations.
"""
from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.models import CanonicalMessage
from archive_sync_engine.models.ids import MessageId

from .base import SyncOperation


@dataclass(frozen=True, slots=True)
class CreateMessageOperation(SyncOperation):
    """
    Create a message.
    """

    message: CanonicalMessage
    include_attachments: bool = False


@dataclass(frozen=True, slots=True)
class EditMessageOperation(SyncOperation):
    """
    Edit the message content state.

    canonical_fingerprint is supplied when this operation also completes
    the complete canonical message baseline. It is omitted when reaction
    or pin operations still need to be executed.
    """

    message: CanonicalMessage
    canonical_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class DeleteMessageOperation(SyncOperation):
    """
    Delete a message.
    """

    message_id: MessageId


@dataclass(frozen=True, slots=True)
class PinMessageOperation(SyncOperation):
    """
    Pin a message.

    canonical_fingerprint is supplied when pinning completes the complete
    canonical message baseline.
    """

    message_id: MessageId
    canonical_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class UnpinMessageOperation(SyncOperation):
    """
    Unpin a message.

    canonical_fingerprint is supplied when unpinning completes the complete
    canonical message baseline.
    """

    message_id: MessageId
    canonical_fingerprint: str | None = None
