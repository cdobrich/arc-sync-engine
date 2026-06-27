"""
Canonical conversation model.

A CanonicalConversation represents any container that can hold messages.

The engine intentionally models direct messages, group chats, channels,
and threads as conversations. Platform adapters are responsible for
mapping platform-specific concepts into this canonical representation.

Threads are represented by setting parent_id to the parent conversation's
identifier. Platforms without thread support simply leave parent_id as None.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .enums import ConversationType
from .ids import ConversationId

from ._validation import require_timezone_aware


@dataclass(frozen=True, slots=True)
class CanonicalConversation:
    """
    Immutable canonical conversation.

    Every message belongs to exactly one CanonicalConversation.

    The conversation_type preserves the semantic type of the original
    conversation.

    Threads are represented as conversations whose parent_id refers to
    another conversation.
    """

    id: ConversationId
    conversation_type: ConversationType
    title: str | None = None
    parent_id: ConversationId | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        """
        Validate canonical conversation invariants.
        """
        
        if self.created_at is not None:
            require_timezone_aware(
                "created_at",
                self.created_at,
            )

        if self.parent_id == self.id:
            raise ValueError(
                "A conversation cannot be its own parent."
            )

        if (
            self.conversation_type == ConversationType.THREAD
            and self.parent_id is None
        ):
            raise ValueError(
                "Thread conversations must specify a parent_id."
            )

        if (
            self.conversation_type != ConversationType.THREAD
            and self.parent_id is not None
        ):
            raise ValueError(
                "Only thread conversations may specify a parent_id."
            )
