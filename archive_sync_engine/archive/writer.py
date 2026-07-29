"""
Archive Writer.

The ArchiveWriter incrementally persists canonical entities into an
Archive Package.

Unlike the previous ArchiveBuilder implementation, entities are written
immediately to persistent storage rather than accumulated in memory.

ArchiveWriter is responsible for:

    * accepting canonical entities;
    * coordinating aggregate persistence;
    * owning transaction boundaries; and
    * managing the lifetime of an ArchiveStore.

ArchiveWriter does not perform SQL operations directly. Those are
delegated to ArchiveStore.
"""

from __future__ import annotations

from archive_sync_engine.models import (
    CanonicalConversation,
    CanonicalIdentity, CanonicalMessage,
)

from .paths import ArchivePaths
from .store import ArchiveStore


class ArchiveWriter:
    """
    Public write façade for an Archive Package.

    Canonical entities are persisted immediately through ArchiveStore.

    Transaction boundaries are explicitly controlled by the caller.
    """

    def __init__(
        self,
        paths: ArchivePaths,
    ) -> None:

        self._paths = paths
        self._paths.ensure_exists()

        self._store = ArchiveStore.create(
            paths,
        )

    #
    # Conversations
    #

    def add_conversation(
        self,
        conversation: CanonicalConversation,
    ) -> None:
        """
        Persist a canonical conversation.
        """

        self._store.insert_conversation(
            conversation,
        )

    #
    # Identities
    #

    def add_identity(
        self,
        identity: CanonicalIdentity,
    ) -> None:
        """
        Persist a canonical identity.
        """

        self._store.insert_identity(
            identity,
        )

    #
    # Messages
    #

    def add_message(
            self,
            message: CanonicalMessage,
    ) -> None:
        """
        Persist a canonical message.
        """

        self._store.insert_message(
            message,
        )

    #
    # Transactions
    #

    def commit(
        self,
    ) -> None:
        """
        Commit the current transaction.
        """

        self._store.commit()

    def rollback(
        self,
    ) -> None:
        """
        Roll back the current transaction.
        """

        self._store.rollback()

    #
    # Lifecycle
    #

    def close(
        self,
    ) -> None:
        """
        Close the underlying ArchiveStore.
        """

        self._store.close()

    def __enter__(
        self,
    ) -> "ArchiveWriter":

        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> None:

        if exc_type is None:
            self.commit()
        else:
            self.rollback()

        self.close()
        

