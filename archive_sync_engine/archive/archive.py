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

from archive_sync_engine.models import CanonicalConversation, CanonicalIdentity, CanonicalMessage, CanonicalAttachment
from archive_sync_engine.models.ids import ConversationId, IdentityKey, MessageId, AttachmentId
from . import ArchiveManifest
from .package import ArchivePackage

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
        self._package = ArchivePackage(
            paths,
        )

        self._manifest = (
            self._package.load_manifest()
        )

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
    # Attachments
    #

    def attachment(
            self,
            attachment_id: AttachmentId,
    ) -> CanonicalAttachment | None:
        """
        Retrieve a canonical attachment.
        """

        return self._store.get_attachment(
            attachment_id,
        )

    def iter_attachments(
            self,
    ) -> Iterator[CanonicalAttachment]:
        """
        Iterate over every canonical attachment.
        """

        return self._store.iter_attachments()

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
    # Manifest
    #

    @property
    def manifest(
            self,
    ) -> ArchiveManifest:
        """
        Return the Archive Package manifest.
        """

        return self._manifest

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

        return self._reconstruct_message(
            message_id,
        )

    def _reconstruct_message(
        self,
        message_id: MessageId,
    ) -> CanonicalMessage | None:
        """
        Reconstruct a complete CanonicalMessage aggregate from
        normalized persistence.
        """

        #
        # Load the message row.
        #

        message = self._store.get_message(
            message_id,
        )

        if message is None:
            return None

        #
        # Reconstruct attachments.
        #

        attachments = tuple(
            self._store.attachments_for_message(
                message.id,
            )
        )

        #
        # Reconstruct reactions. TODO.
        #

        reactions = ()

        #
        # Return the reconstructed aggregate.
        #

        return CanonicalMessage(
            id=message.id,
            conversation_id=message.conversation_id,
            identity_key=message.identity_key,
            created_at=message.created_at,
            edited_at=message.edited_at,
            reply_to=message.reply_to,
            content=message.content,
            attachments=attachments,
            reactions=reactions,
        )

    def iter_messages(
            self,
    ) -> Iterator[
        CanonicalMessage
    ]:
        """
        Iterate over every canonical message.
        """

        for message in self._store.iter_messages():

            reconstructed = self._reconstruct_message(
                message.id,
            )

            if reconstructed is not None:
                yield reconstructed