"""
Canonical importer implementation.

CanonicalImporter provides the first complete import vertical slice.

A SourceAdapter is responsible for reading platform state and translating
that state into canonical models. CanonicalImporter is responsible for
persisting those canonical models into an Archive Package.

Attachment metadata is persisted as part of message persistence.
Attachment bytes are intentionally handled by a later AssetStore
vertical slice.
"""

from __future__ import annotations

from archive_sync_engine.adapters import SourceAdapter
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.asset_store import AssetStore

from .importer import Importer
from archive_sync_engine.models import CanonicalConversation

class CanonicalImporter(Importer):
    """
    Import canonical entities supplied by a SourceAdapter.

    Import proceeds in dependency order:

        identities
            ↓
        conversations
            ↓
        messages
            ↓
        attachment metadata

    The SourceAdapter remains responsible for translating platform-specific
    state into canonical models.

    ArchiveWriter remains responsible for persistence.

    AssetStore is accepted as part of the importer boundary, but attachment
    byte persistence is not yet implemented. Attachment metadata is
    persisted through ArchiveWriter.add_message().
    """

    def import_source(
        self,
        source: SourceAdapter,
        writer: ArchiveWriter,
        asset_store: AssetStore,
    ) -> None:
        """
        Import all canonical information available from the source.

        Identities are imported first because messages reference logical
        identities.

        Conversations are imported before their messages.

        Messages are enumerated per conversation because SourceAdapter
        defines message traversal at the conversation boundary.

        Attachment metadata is persisted by ArchiveWriter when each
        message is persisted.
        """

        self._import_identities(
            source,
            writer,
        )

        self._import_conversations(
            source,
            writer,
        )

    def _import_identities(
        self,
        source: SourceAdapter,
        writer: ArchiveWriter,
    ) -> None:
        """
        Import every identity exposed by the source.
        """

        for identity in source.iter_identities():
            writer.add_identity(
                identity,
            )

    def _import_conversations(
        self,
        source: SourceAdapter,
        writer: ArchiveWriter,
    ) -> None:
        """
        Import every conversation and its messages.
        """

        for conversation in source.iter_conversations():

            writer.add_conversation(
                conversation,
            )

            self._import_messages(
                source,
                conversation,
                writer,
            )

    def _import_messages(
        self,
        source: SourceAdapter,
        conversation: CanonicalConversation,
        writer: ArchiveWriter,
    ) -> None:
        """
        Import every message belonging to a conversation.

        ArchiveWriter.add_message() persists the message itself,
        attachment metadata, attachment relationships, and reactions
        belonging to the message.
        """

        for message in source.iter_messages(
            conversation,
        ):
            writer.add_message(
                message,
            )