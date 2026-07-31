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
    CanonicalIdentity, CanonicalMessage, CanonicalAttachment,
)
from .package import ArchivePackage

from .paths import ArchivePaths
from .store import ArchiveStore
from archive_sync_engine.models.ids import AttachmentId, IdentityKey, EmojiId
from archive_sync_engine.models.provenance import CanonicalProvenance, CanonicalTransfer


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

        self._package = ArchivePackage(
            paths,
        )

    #
    # Attachments
    #

    def add_attachment(
            self,
            attachment: CanonicalAttachment,
    ) -> None:
        """
        Persist a canonical attachment.
        """

        self._store.insert_attachment(
            attachment,
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
    # Manifest
    #

    def _save_manifest(
            self,
    ) -> None:
        """
        Save the Archive Package manifest.
        """

        manifest = (
            self._package.create_manifest()
        )

        self._package.save_manifest(
            manifest,
        )

    #
    # Messages
    #

    def add_message(
            self,
            message: CanonicalMessage,
    ) -> None:
        """
        Persist a canonical message aggregate.
        """

        #
        # Persist the message.
        #

        self._store.insert_message(
            message,
        )

        #
        # Persist every attachment and its relationship.
        #

        seen_attachment_ids: set[
            AttachmentId
        ] = set()

        for attachment_index, attachment in enumerate(
                message.attachments,
        ):

            #
            # Prevent duplicate attachment IDs within a single canonical message.
            #

            if attachment.id in seen_attachment_ids:
                raise ValueError(
                    "Duplicate attachment "
                    f"{attachment.id} in "
                    f"message {message.id}."
                )

            seen_attachment_ids.add(
                attachment.id,
            )

            #
            # Persist metadata.
            #

            self._store.insert_attachment(
                attachment,
            )

            #
            # Persist relationship.
            #

            self._store.insert_message_attachment(
                message.id,
                attachment.id,
                attachment_index,
            )

    #
    # Provenance
    #

    def record_transfer(
            self,
            transfer: CanonicalTransfer,
    ) -> None:
        """
        Persist one provenance transfer record.

        Existing provenance history is preserved. This method is intended
        for incremental recording of archive activity, including
        semi-continuous export or duplication operations.
        """

        self._store.insert_provenance_transfer(
            transfer,
        )

    def write_provenance(
            self,
            provenance: CanonicalProvenance,
    ) -> None:
        """
        Persist canonical archive provenance.

        Each transfer in the provenance history is stored as an
        individual historical record. The caller controls transaction
        boundaries through commit() and rollback().
        """

        for transfer in provenance.history:
            self._store.insert_provenance_transfer(
                transfer,
            )

    #
    # Reactions
    #

    def _persist_message_reactions(
            self,
            message: CanonicalMessage,
    ) -> None:
        """
        Persist every reaction belonging to a message.
        """

        for reaction in message.reactions:
            self._store.insert_message_reaction(
                message.id,
                reaction,
            )

    def _validate_message_reactions(
            self,
            message: CanonicalMessage,
    ) -> None:
        """
        Validate reaction invariants for a message.
        """

        seen: set[
            tuple[
                IdentityKey,
                str,
                EmojiId | None,
            ]
        ] = set()

        for reaction in message.reactions:

            key = (
                reaction.identity_key,
                reaction.emoji,
                reaction.emoji_id,
            )

            if key in seen:
                raise ValueError(
                    f"Duplicate reaction on "
                    f"message {message.id}."
                )

            seen.add(
                key,
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
        

