"""
Read-only interface to an Archive Package.

The Archive is the source of truth for the Archive Sync Engine.

It stores canonical entities independently of any source or destination
platform.

The Archive intentionally exposes entity-oriented operations rather than
platform-specific behavior.
"""

from __future__ import annotations

from collections.abc import Iterator

from archive_sync_engine.models import CanonicalConversation, CanonicalIdentity, CanonicalMessage
from archive_sync_engine.models.ids import ConversationId, IdentityKey, MessageId

from .paths import ArchivePaths
from .store import ArchiveStore


class Archive:
    """
    Read-only view of an Archive Package.
    """

    def __init__(
        self,
        paths: ArchivePaths,
    ) -> None:

        self._store = ArchiveStore.open(paths)

    #
    # Conversations
    #

    def conversation(
        self,
        conversation_id: ConversationId,
    ) -> CanonicalConversation | None:
        """
        Retrieve a conversation by its canonical identifier.
        """

        return self._store.get_conversation(
            conversation_id,
        )

    def iter_conversations(
        self,
    ) -> Iterator[CanonicalConversation]:
        """
        Iterate over every conversation in the archive.
        """

        return self._store.iter_conversations()

    #
    # Lifecycle
    #

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> "Archive":
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> None:
        self.close()

    #
    # Identities
    #

    def identity(
        self,
        identity_key: IdentityKey,
    ) -> CanonicalIdentity | None:
        """
        Retrieve a canonical identity.
        """

        return self._store.get_identity(identity_key)
            

    def iter_identities(
        self,
    ) -> Iterator[CanonicalIdentity]:
        """
        Iterate over all identities.
        """

        return self._store.iter_identities()

    #
    # Messages
    #

    def message(
            self,
            message_id: MessageId,
    ) -> CanonicalMessage | None:
        """
        Retrieve a canonical message.
        """

        return self._store.get_message(
            message_id,
        )

    def iter_messages(
            self,
    ) -> Iterator[CanonicalMessage]:
        """
        Iterate over every canonical message.
        """

        return self._store.iter_messages()