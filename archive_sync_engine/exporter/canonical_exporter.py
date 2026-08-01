"""
Canonical export pipeline.

CanonicalExporter reads canonical information from an Archive and
reproduces it through a DestinationAdapter.

The exporter does not perform planning or reconciliation decisions.
Those responsibilities belong to the synchronization layer.

This performs initial archive reproduction only.
"""

from __future__ import annotations

from archive_sync_engine.adapters import DestinationAdapter
from archive_sync_engine.archive import Archive
from archive_sync_engine.asset_store import AssetStore


class CanonicalExporter:
    """
    Export canonical archive contents to a destination adapter.
    """

    def export(
        self,
        archive: Archive,
        destination: DestinationAdapter,
        asset_store: AssetStore,
    ) -> None:
        """
        Reproduce the canonical archive at the destination.

        Export order is:

            identities
                ↓
            conversations
                ↓
            attachments
                ↓
            messages

        The destination adapter is responsible for translating
        canonical models into platform-specific operations.
        """

        #
        # Identities
        #

        for identity in archive.iter_identities():

            destination.create_identity(
                identity,
            )

        #
        # Conversations
        #

        for conversation in archive.iter_conversations():

            destination.create_conversation(
                conversation,
            )

            #
            # Messages
            #

            for message in archive.iter_messages_for_conversation(
                conversation.id,
            ):

                #
                # Attachments
                #
                # Attachment metadata belongs to the canonical message,
                # while the actual bytes are owned by AssetStore.
                #

                for attachment in message.attachments:

                    data = asset_store.get(
                        attachment.sha256,
                    )

                    destination.upload_attachment(
                        attachment,
                        data,
                    )

                #
                # Message
                #

                destination.create_message(
                    message,
                )

                #
                # Pin state
                #

                if message.pinned:

                    destination.pin_message(
                        message.id,
                    )

                #
                # Reactions
                #

                for reaction in message.reactions:

                    destination.add_reaction(
                        message.id,
                        reaction,
                    )