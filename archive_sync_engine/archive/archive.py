"""
Archive interface.

The Archive is the source of truth for the Archive Sync Engine.

It stores canonical entities independently of any source or destination
platform.

The Archive intentionally exposes entity-oriented operations rather than
platform-specific behaviour.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
)


class Archive(ABC):
    """
    Canonical archive interface.
    """

    #
    # Conversations
    #

    @abstractmethod
    def add_conversation(
        self,
        conversation: CanonicalConversation,
    ) -> None:
        """
        Store a canonical conversation.
        """
        raise NotImplementedError

    #
    # Identities
    #

    @abstractmethod
    def add_identity(
        self,
        identity: CanonicalIdentity,
    ) -> None:
        """
        Store a canonical identity.
        """
        raise NotImplementedError

    #
    # Messages
    #

    @abstractmethod
    def add_message(
        self,
        message: CanonicalMessage,
    ) -> None:
        """
        Store a canonical message.
        """
        raise NotImplementedError

    #
    # Attachments
    #

    @abstractmethod
    def add_attachment(
        self,
        attachment: CanonicalAttachment,
    ) -> None:
        """
        Store a canonical attachment.
        """
        raise NotImplementedError