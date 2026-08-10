"""
Abstract destination adapter interface.

A DestinationAdapter receives canonical models from the Archive Engine
and reproduces them on a destination platform.

Destination adapters are responsible only for translating canonical
models into platform-specific operations. They never perform planning,
reconciliation, or synchronization decisions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
    CanonicalReaction,
)
from archive_sync_engine.models.ids import ConversationId, IdentityKey, MessageId

from .capabilities import DestinationCapabilities
from .references import (
    DestinationAttachmentRef,
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)

class DestinationAdapter(ABC):
    """
    Abstract interface implemented by every destination platform adapter.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Human-readable adapter name.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def capabilities(self) -> DestinationCapabilities:
        """
        Immutable description of the destination platform's capabilities.
        """
        raise NotImplementedError

    @abstractmethod
    def create_conversation(
        self,
        conversation: CanonicalConversation,
    ) -> DestinationConversationRef:
        """
        Create a conversation.
        """
        raise NotImplementedError

    @abstractmethod
    def update_conversation(
        self,
        conversation: CanonicalConversation,
    ) -> None:
        """
        Update an existing conversation.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_conversation(
        self,
        conversation_id: ConversationId,
    ) -> None:
        """
        Delete an existing conversation.
        """
        raise NotImplementedError

    @abstractmethod
    def create_identity(
        self,
        identity: CanonicalIdentity,
    ) -> DestinationIdentityRef:
        """
        Create or reconcile a logical identity on the destination
        platform.
        """
        raise NotImplementedError

    @abstractmethod
    def update_identity(
        self,
        identity: CanonicalIdentity,
    ) -> None:
        """
        Update an existing destination identity.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_identity(
        self,
        identity_key: IdentityKey,
    ) -> None:
        """
        Delete an existing destination identity.
        """
        raise NotImplementedError

    @abstractmethod
    def upload_attachment(
        self,
        attachment: CanonicalAttachment,
        data: bytes,
    ) -> DestinationAttachmentRef:
        """
        Upload an attachment to the destination platform.

        The supplied bytes correspond to the attachment's SHA-256
        digest.
        """
        raise NotImplementedError

    @abstractmethod
    def add_attachment(
        self,
        message_id: MessageId,
        attachment: CanonicalAttachment,
        data: bytes,
    ) -> DestinationAttachmentRef:
        """
        Add an attachment to an existing destination message.

        The supplied bytes correspond to the attachment's SHA-256
        digest.
        """
        raise NotImplementedError

    @abstractmethod
    def remove_attachment(
        self,
        message_id: MessageId,
        attachment: CanonicalAttachment,
    ) -> None:
        """
        Remove a canonical attachment from an existing destination message.
        """
        raise NotImplementedError

    @abstractmethod
    def reorder_attachments(
        self,
        message_id: MessageId,
        attachments: tuple[CanonicalAttachment, ...],
    ) -> None:
        """Set the complete canonical attachment order for a message."""
        raise NotImplementedError

    @abstractmethod
    def create_message(
        self,
        message: CanonicalMessage,
    ) -> DestinationMessageRef:
        """
        Create a message on the destination platform.
        """
        raise NotImplementedError

    @abstractmethod
    def edit_message(
        self,
        message: CanonicalMessage,
    ) -> None:
        """
        Update an existing destination message.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_message(
        self,
        message_id: MessageId,
    ) -> None:
        """
        Delete an existing destination message.
        """
        raise NotImplementedError

    @abstractmethod
    def set_message_reply(
        self,
        message: DestinationMessageRef,
        reply_to: DestinationMessageRef | None,
    ) -> None:
        """
        Set or clear the reply relationship of a destination message.

        Destination references are used because canonical message IDs do
        not identify objects on the destination platform.
        """
        raise NotImplementedError

    @abstractmethod
    def pin_message(
        self,
        message_id: MessageId,
    ) -> None:
        """
        Pin a destination message.
        """
        raise NotImplementedError

    @abstractmethod
    def unpin_message(
        self,
        message_id: MessageId,
    ) -> None:
        """
        Unpin a destination message.
        """
        raise NotImplementedError

    @abstractmethod
    def add_reaction(
        self,
        message_id: MessageId,
        reaction: CanonicalReaction,
    ) -> None:
        """
        Add a reaction to a destination message.
        """
        raise NotImplementedError

    @abstractmethod
    def remove_reaction(
        self,
        message_id: MessageId,
        reaction: CanonicalReaction,
    ) -> None:
        """
        Remove a reaction from a destination message.
        """
        raise NotImplementedError