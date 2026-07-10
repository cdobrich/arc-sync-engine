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
)

from .references import (
    DestinationAttachmentRef,
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)

from .capabilities import DestinationCapabilities


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
        Create a destination conversation corresponding to the supplied
        canonical conversation.
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

        Adapters for platforms that do not expose identity management
        may treat this operation as a no-op.
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
        message: CanonicalMessage,
    ) -> None:
        """
        Delete a destination message.
        """
        raise NotImplementedError

    @abstractmethod
    def pin_message(
        self,
        message: CanonicalMessage,
    ) -> None:
        """
        Pin a destination message.
        """
        raise NotImplementedError

    @abstractmethod
    def add_reactions(
        self,
        message: CanonicalMessage,
    ) -> None:
        """
        Synchronize the reactions associated with a message.
        """
        raise NotImplementedError
