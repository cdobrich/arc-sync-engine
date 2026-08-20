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

    def validate_operations(self, operations) -> None:
        """Validate a complete planned operation stream before execution.

        Destination adapters may reject destination-specific configuration
        problems that cannot be represented by static capabilities alone.
        The default implementation accepts every operation.

        Validation is performed against the complete plan so a destination
        can reject an otherwise executable plan before any side effects occur.
        """
        del operations

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
        destination: DestinationConversationRef,
    ) -> None:
        """
        Update an existing conversation.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_conversation(
        self,
        destination: DestinationConversationRef,
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
        destination: DestinationIdentityRef,
    ) -> None:
        """
        Update an existing destination identity.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_identity(
        self,
        destination: DestinationIdentityRef,
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
        message: DestinationMessageRef,
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
        message: DestinationMessageRef,
        attachment: CanonicalAttachment,
    ) -> None:
        """
        Remove a canonical attachment from an existing destination message.
        """
        raise NotImplementedError

    @abstractmethod
    def reorder_attachments(
        self,
        message: DestinationMessageRef,
        attachments: tuple[CanonicalAttachment, ...],
    ) -> None:
        """Set the complete canonical attachment order for a message."""
        raise NotImplementedError

    @abstractmethod
    def create_message(
        self,
        message: CanonicalMessage,
        destination: DestinationConversationRef,
        attachments: tuple[tuple[CanonicalAttachment, bytes], ...] = (),
        reply_to: DestinationMessageRef | None = None,
    ) -> DestinationMessageRef:
        """
        Create a message on the destination platform.

        ``reply_to`` is an execution-local destination reference used only
        when the destination can establish a reply relationship during
        message creation.
        """
        raise NotImplementedError

    @abstractmethod
    def edit_message(
        self,
        message: CanonicalMessage,
        destination: DestinationMessageRef,
    ) -> None:
        """
        Update an existing destination message.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_message(
        self,
        destination: DestinationMessageRef,
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
        message: DestinationMessageRef,
    ) -> None:
        """
        Pin a destination message.
        """
        raise NotImplementedError

    @abstractmethod
    def unpin_message(
        self,
        message: DestinationMessageRef,
    ) -> None:
        """
        Unpin a destination message.
        """
        raise NotImplementedError

    @abstractmethod
    def add_reaction(
        self,
        message: DestinationMessageRef,
        reaction: CanonicalReaction,
    ) -> None:
        """
        Add a reaction to a destination message.
        """
        raise NotImplementedError

    @abstractmethod
    def remove_reaction(
        self,
        message: DestinationMessageRef,
        reaction: CanonicalReaction,
    ) -> None:
        """
        Remove a reaction from a destination message.
        """
        raise NotImplementedError
