"""
Canonical model definitions.

These immutable models form the platform-independent language spoken by
every component of the Archive-Sync Engine.

Adapters convert platform-specific objects into canonical models.
The planner and executor operate exclusively on canonical models.
The archive persists canonical models.
"""

from .attachment import CanonicalAttachment
from .conversation import CanonicalConversation
from .custom_emoji import CanonicalCustomEmoji
from .enums import ConversationType
from .identity import CanonicalIdentity
from .message import CanonicalMessage
from .reaction import CanonicalReaction

__all__ = [
    "CanonicalAttachment",
    "CanonicalConversation",
    "CanonicalCustomEmoji",
    "CanonicalIdentity",
    "CanonicalMessage",
    "CanonicalReaction",
    "ConversationType",
]
