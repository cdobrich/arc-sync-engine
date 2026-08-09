"""
Synchronization operations.

SyncOperations are immutable descriptions of work produced by the Planner.

The OperationExecutor consumes SyncOperations and applies them to a DestinationAdapter.

Unlike ImportOperations, SyncOperations represent synchronization from the canonical Archive to one or more destination platforms.
"""

from .base import SyncOperation

from .conversation import (
    CreateConversationOperation,
    UpdateConversationOperation,
    DeleteConversationOperation,
)

from .identity import (
    CreateIdentityOperation,
    UpdateIdentityOperation,
)

from .message import (
    CreateMessageOperation,
    EditMessageOperation,
    DeleteMessageOperation,
    PinMessageOperation,
    UnpinMessageOperation,
)

from .reaction import (
    AddReactionOperation,
    RemoveReactionOperation,
)

from .attachment import (
    AddAttachmentOperation,
    RemoveAttachmentOperation,
    ReorderAttachmentsOperation,
)

from .reply import SetMessageReplyOperation

__all__ = [
    "SyncOperation",

    "CreateConversationOperation",
    "UpdateConversationOperation",
    "DeleteConversationOperation",

    "CreateIdentityOperation",
    "UpdateIdentityOperation",

    "CreateMessageOperation",
    "EditMessageOperation",
    "DeleteMessageOperation",
    "PinMessageOperation",
    "UnpinMessageOperation",

    "AddReactionOperation",
    "RemoveReactionOperation",

    "AddAttachmentOperation",
    "RemoveAttachmentOperation",
    "ReorderAttachmentsOperation",

    "SetMessageReplyOperation",
]
