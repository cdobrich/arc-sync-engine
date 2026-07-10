"""
Shared enumerations used by canonical models.
"""

from enum import Enum


class ConversationType(str, Enum):
    """
    Describes the original semantic type of a conversation.

    This value preserves the conversation semantics as they existed on
    the source platform.

    The Archive stores this information even when a destination platform
    cannot represent the same conversation type.

    Destination adapters may use this value to make informed decisions
    when mapping conversations onto platforms with different capabilities.

    THREAD conversations are represented by setting parent_id to another
    CanonicalConversation.
    """

    DIRECT = "direct"
    GROUP = "group"
    CHANNEL = "channel"
    THREAD = "thread"
