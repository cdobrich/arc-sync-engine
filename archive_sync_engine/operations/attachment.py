"""Message attachment synchronization operations."""
from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.models import CanonicalAttachment
from archive_sync_engine.models.ids import MessageId

from .base import SyncOperation


@dataclass(frozen=True, slots=True)
class AddAttachmentOperation(SyncOperation):
    """Add one canonical attachment to an existing message.

    ``resulting_attachments`` is the canonical attachment baseline after
    this operation succeeds. ``canonical_fingerprint`` is supplied only
    when this operation completes the complete canonical message baseline.
    """

    message_id: MessageId
    attachment: CanonicalAttachment
    resulting_attachments: tuple[CanonicalAttachment, ...] | None = None
    canonical_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class RemoveAttachmentOperation(SyncOperation):
    """Remove one canonical attachment from an existing message."""

    message_id: MessageId
    attachment: CanonicalAttachment
    resulting_attachments: tuple[CanonicalAttachment, ...] | None = None
    canonical_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class ReorderAttachmentsOperation(SyncOperation):
    """Reorder the canonical attachments on an existing message.

    ``attachments`` is the complete canonical attachment ordering that must
    be established by the destination. ``canonical_fingerprint`` is supplied
    when this operation completes the complete canonical message baseline.
    """

    message_id: MessageId
    attachments: tuple[CanonicalAttachment, ...]
    canonical_fingerprint: str | None = None
