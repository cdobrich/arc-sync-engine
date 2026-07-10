"""
Abstract source adapter interface.

A SourceAdapter reads data from a source platform and translates it into
canonical models understood by the Archive Engine.

Source adapters are responsible only for reading platform state.
They never perform write operations.

All platform-specific representations must be converted into canonical
models before crossing the adapter boundary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
)


class SourceAdapter(ABC):
    """
    Abstract interface implemented by every source platform adapter.

    The Archive Engine communicates exclusively through this interface
    when importing data from a platform.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Human-readable adapter name.

        Examples:

            "Discord"
            "Fluxer"
        """
        raise NotImplementedError

    @abstractmethod
    def iter_conversations(self) -> Iterable[CanonicalConversation]:
        """
        Enumerate every conversation available from the source.
        """
        raise NotImplementedError

    @abstractmethod
    def iter_identities(self) -> Iterable[CanonicalIdentity]:
        """
        Enumerate every logical identity referenced by the source.
        """
        raise NotImplementedError

    @abstractmethod
    def iter_messages(
        self,
        conversation: CanonicalConversation,
    ) -> Iterable[CanonicalMessage]:
        """
        Enumerate every message belonging to a conversation.
        """
        raise NotImplementedError

    @abstractmethod
    def attachment_bytes(
        self,
        attachment: CanonicalAttachment,
    ) -> bytes:
        """
        Retrieve the binary contents of an attachment.

        The returned bytes must correspond to the attachment's SHA-256
        digest stored in the canonical model.
        """
        raise NotImplementedError
