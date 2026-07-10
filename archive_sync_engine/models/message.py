"""
Canonical message model.

CanonicalMessage is the central value object of the Archive-Sync Engine.

Every message belongs to exactly one conversation and one logical
identity. Relationships between messages are expressed using canonical
identifiers rather than embedded objects.

The canonical model preserves message semantics while remaining
independent of any specific chat platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .attachment import CanonicalAttachment
from .ids import (
    ConversationId,
    DestinationId,
    IdentityKey,
    MessageId,
)
from .reaction import CanonicalReaction

from ._validation import require_timezone_aware


@dataclass(frozen=True, slots=True)
class CanonicalMessage:
    """
    Immutable canonical message.

    All timestamps are timezone-aware UTC datetimes.

    destination_id represents the logical destination conversation
    selected by the synchronization planner. It is not the identifier
    of a destination-platform message.
    """

    id: MessageId
    conversation_id: ConversationId
    identity_key: IdentityKey
    content: str
    created_at: datetime
    destination_id: DestinationId | None = None
    edited_at: datetime | None = None
    reply_to: MessageId | None = None
    pinned: bool = False

    attachments: tuple[CanonicalAttachment, ...] = field(
        default_factory=tuple
    )

    reactions: tuple[CanonicalReaction, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        """
        Validate canonical message invariants.
        """

        require_timezone_aware("created_at", self.created_at)

        if self.edited_at is not None:
            require_timezone_aware("edited_at", self.edited_at)

            if self.edited_at < self.created_at:
                raise ValueError(
                    "edited_at cannot be earlier than created_at."
                )

        if self.reply_to == self.id:
            raise ValueError(
                "A message cannot reply to itself."
            )

        if not self.content and not self.attachments:
            raise ValueError(
                "A message must contain text or at least one attachment."
            )
