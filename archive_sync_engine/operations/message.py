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


@dataclass(frozen=True, slots=True)
class EditMessageOperation(SyncOperation):
    """
    Edit a message.
    """

    message: CanonicalMessage


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
    """

    message_id: MessageId


@dataclass(frozen=True, slots=True)
class UnpinMessageOperation(SyncOperation):
    """
    Unpin a message.
    """

    message_id: MessageId
