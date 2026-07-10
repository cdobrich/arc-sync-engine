"""
Strongly typed identifier aliases used throughout the Archive-Sync Engine.

Identifiers are intentionally opaque strings. The engine never interprets
their contents; adapters and the archive are responsible for resolving them.
"""

from typing import NewType

ConversationId = NewType("ConversationId", str)
MessageId = NewType("MessageId", str)
AttachmentId = NewType("AttachmentId", str)
IdentityKey = NewType("IdentityKey", str)
EmojiId = NewType("EmojiId", str)
DestinationId = NewType("DestinationId", str)
