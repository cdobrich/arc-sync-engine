"""
Atomic operations used internally by the import pipeline.

ImportOperations represent small units of acquisition work.

Unlike SyncOperations, these operations never describe synchronization.

They are consumed exclusively by the ImportCoordinator and Importer.

They are not visible outside the import subsystem.
"""

from .attachment import ImportAttachmentOperation
from .base import ImportOperation
from .conversation import ImportConversationOperation
from .identity import ImportIdentityOperation
from .message import ImportMessageOperation

__all__ = [
    "ImportOperation",
    "ImportConversationOperation",
    "ImportIdentityOperation",
    "ImportMessageOperation",
    "ImportAttachmentOperation",
]
