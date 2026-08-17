"""
Canonical import pipeline.

CanonicalImporter acquires canonical data from a SourceAdapter and
persists it into an Archive.

Import order is deliberately deterministic:

    identities
        ↓
    conversations
        ↓
    messages
        ↓
    attachment bytes

The importer coordinates acquisition and persistence but does not
interpret platform-specific data. The SourceAdapter has already
translated platform data into canonical models.

Import progress is reported through an optional callback. Persistence
of that progress remains the responsibility of the coordinator.
"""

from __future__ import annotations

from collections.abc import Callable, Sized

from archive_sync_engine.adapters import SourceAdapter
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.asset_store import AssetStore
from archive_sync_engine.importer.progress import ImportProgress
from archive_sync_engine.importer.state import ImportState


class CanonicalImporter:
    """
    Import canonical source data into an Archive.

    CanonicalImporter owns the import traversal order. Persistence is
    delegated to ArchiveWriter, while attachment bytes are delegated
    to AssetStore.

    Import progress is reported through an optional callback. The
    importer does not persist progress itself.
    """

    def import_source(
        self,
        source: SourceAdapter,
        writer: ArchiveWriter,
        asset_store: AssetStore,
        on_progress: Callable[[ImportState], None] | None = None,
        on_status: Callable[[ImportProgress], None] | None = None,
        resume_state: ImportState | None = None,
    ) -> None:
        """
        Import all canonical information available from a source.

        Identities are imported first.

        Each conversation is then imported followed by every message
        belonging to that conversation.

        Attachment metadata is persisted as part of each message.

        Attachment bytes are retrieved from the SourceAdapter and
        persisted through AssetStore.

        When a message and all of its attachments have been successfully
        persisted, on_progress is called with an opaque ImportState
        identifying the completed conversation and message.
        """

        #
        # Identities
        #
        # A resumed import already has all identities from the original
        # import pass because identities are traversed before messages.
        # Skip them during resume so we do not reinsert already-persisted
        # records.
        #

        if resume_state is None:
            if on_status is not None:
                on_status(ImportProgress(phase="identities", current=0))
            identity_count = 0
            for identity in source.iter_identities():
                writer.add_identity(identity)
                identity_count += 1
                if on_status is not None:
                    on_status(
                        ImportProgress(
                            phase="identities",
                            current=identity_count,
                            detail=str(identity.identity_key),
                        )
                    )

        #
        # Conversations and messages
        #
        # The SourceAdapter defines the canonical traversal boundary:
        # messages are requested for a specific canonical conversation.
        #

        resume_conversation_id = None
        resume_message_id = None
        if resume_state is not None:
            resume_conversation_id = resume_state.payload.get(
                "conversation_id",
            )
            resume_message_id = resume_state.payload.get(
                "message_id",
            )

        resume_reached = resume_state is None

        conversations = source.iter_conversations()
        conversation_total = len(conversations) if isinstance(conversations, Sized) else None
        if on_status is not None:
            on_status(
                ImportProgress(
                    phase="conversations",
                    current=0,
                    total=conversation_total,
                )
            )
        conversation_count = 0

        for conversation in conversations:

            conversation_id = str(conversation.id)
            conversation_count += 1
            if on_status is not None:
                on_status(
                    ImportProgress(
                        phase="conversations",
                        current=conversation_count,
                        total=conversation_total,
                        detail=str(getattr(conversation, "title", None) or conversation.id),
                    )
                )

            resume_conversation = False
            if resume_state is not None and not resume_reached:
                if conversation_id == resume_conversation_id:
                    resume_reached = True
                    resume_conversation = True
                else:
                    continue

            if not resume_conversation:
                writer.add_conversation(conversation)

            skipping_messages = (
                resume_state is not None
                and conversation_id == resume_conversation_id
                and resume_message_id is not None
            )

            messages = source.iter_messages(conversation)
            message_total = len(messages) if isinstance(messages, Sized) else None
            message_count = 0
            if on_status is not None:
                on_status(
                    ImportProgress(
                        phase="messages",
                        current=0,
                        total=message_total,
                        detail=conversation_id,
                    )
                )

            for message in messages:

                if skipping_messages:
                    if str(message.id) == str(resume_message_id):
                        skipping_messages = False
                        continue
                    continue

                #
                # Persist the complete canonical message aggregate.
                #
                # ArchiveWriter also persists attachment metadata and
                # message/attachment relationships.
                #

                writer.add_message(
                    message,
                )
                message_count += 1

                #
                # Persist attachment bytes separately from metadata.
                #
                # AssetStore verifies that the retrieved bytes match
                # the canonical attachment SHA-256.
                #

                for attachment_index, attachment in enumerate(
                    message.attachments,
                    start=1,
                ):
                    if on_status is not None:
                        on_status(
                            ImportProgress(
                                phase="attachments",
                                current=attachment_index,
                                total=len(message.attachments),
                                detail=str(attachment.filename),
                            )
                        )

                    content = source.attachment_bytes(
                        attachment,
                    )

                    asset_store.put_attachment(
                        attachment,
                        content,
                    )

                #
                # Report progress only after the complete message
                # aggregate and all attachment bytes have succeeded.
                #
                # The importer does not interpret or persist this state.
                #

                if on_status is not None:
                    on_status(
                        ImportProgress(
                            phase="messages",
                            current=message_count,
                            total=message_total,
                            detail=str(message.id),
                        )
                    )

                if on_progress is not None:

                    on_progress(
                        ImportState(
                            payload={
                                "conversation_id": str(
                                    conversation.id,
                                ),
                                "message_id": str(
                                    message.id,
                                ),
                            },
                        ),
                    )