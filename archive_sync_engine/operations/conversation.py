"""
Conversation synchronization operations.
"""
from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.models import CanonicalConversation
from archive_sync_engine.models.ids import ConversationId

from .base import SyncOperation


@dataclass(frozen=True, slots=True)
class CreateConversationOperation(SyncOperation):
    """
    Create a conversation.
    """

    conversation: CanonicalConversation


@dataclass(frozen=True, slots=True)
class UpdateConversationOperation(SyncOperation):
    """
    Update a conversation.
    """

    conversation: CanonicalConversation


@dataclass(frozen=True, slots=True)
class DeleteConversationOperation(SyncOperation):
    """
    Delete a conversation.
    """

    conversation_id: ConversationId
