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

from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
    CanonicalReaction,
)
from archive_sync_engine.models.ids import (
    AttachmentId,
    ConversationId,
    IdentityKey,
    MessageId,
)
from archive_sync_engine.models.provenance import CanonicalProvenance

from .manifest import ArchiveManifest
from .package import ArchivePackage
from .paths import ArchivePaths
from .recomposer import ArchiveRecomposer
from .store import ArchiveStore


class Archive:
    """
    Read-only view of an Archive Package.
    """

    def __init__(
        self,
        paths: ArchivePaths,
    ) -> None:

        self._store = ArchiveStore.open(
            paths,
        )

        self._package = ArchivePackage(
            paths,
        )

        self._manifest = (
            self._package.load_manifest()
        )

        self._recomposer = ArchiveRecomposer(
            self._store,
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
    ) -> Iterator[
        CanonicalConversation
    ]:
        """
        Iterate over every conversation in the archive.
        """

        return self._store.iter_conversations()

    def iter_messages_for_conversation(
        self,
        conversation_id: ConversationId,
    ) -> Iterator[CanonicalMessage]:
        """
        Iterate over canonical messages belonging to a conversation.
        """

        for message in self._store.iter_messages_for_conversation(
            conversation_id,
        ):
            yield self._recomposer.recompose_message(
                message.id,
            )

    #
    # Lifecycle
    #

    def close(
        self,
    ) -> None:
        self._store.close()

    def __enter__(
        self,
    ) -> "Archive":
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
    ) -> Iterator[
        CanonicalAttachment
    ]:
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

        return self._store.get_identity(
            identity_key,
        )

    def iter_identities(
        self,
    ) -> Iterator[
        CanonicalIdentity
    ]:
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
    # Provenance
    #

    @property
    def provenance(
        self,
    ) -> CanonicalProvenance:
        """
        Return the historical provenance of the Archive Package.

        Provenance records how the archive was imported from source
        systems and subsequently exported or otherwise used with
        destination systems.
        """

        return self._recomposer.recompose_provenance()

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

        return self._recomposer.recompose_message(
            message_id,
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
            yield self._recomposer.recompose_message(
                message.id,
            )

    def message_reactions(
        self,
        message_id: MessageId,
    ) -> Iterator[CanonicalReaction]:
        """
        Iterate over the reactions belonging to a message.
        """

        return self._store.reactions_for_message(
            message_id,
        )