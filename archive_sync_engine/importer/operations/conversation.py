"""
Conversation import operations.
"""

from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.models import CanonicalConversation

from .base import ImportOperation


@dataclass(frozen=True, slots=True)
class ImportConversationOperation(ImportOperation):
    """
    Import a canonical conversation into the Archive.
    """

    conversation: CanonicalConversation