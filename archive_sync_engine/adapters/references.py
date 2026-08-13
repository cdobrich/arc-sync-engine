"""
Opaque references returned by destination adapters.

Destination references identify objects created or resolved on a
destination platform.

They are intentionally separate from canonical model identifiers.
A destination reference must never be treated as a canonical ID.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DestinationConversationRef:
    """
    Opaque reference to a destination conversation.
    """

    id: str


@dataclass(frozen=True, slots=True)
class DestinationIdentityRef:
    """
    Opaque reference to a destination identity.
    """

    id: str


@dataclass(frozen=True, slots=True)
class DestinationMessageRef:
    """
    Opaque reference to a destination message.

    ``conversation_id`` is optional because some destination APIs can address
    messages globally, while others require the containing conversation.
    Destination adapters may populate it when it is known.
    """

    id: str
    conversation_id: str | None = None


@dataclass(frozen=True, slots=True)
class DestinationAttachmentRef:
    """
    Opaque reference to a destination attachment.
    """

    id: str
