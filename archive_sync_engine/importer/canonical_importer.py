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

from collections.abc import Callable, Sized, Iterable

from archive_sync_engine.adapters import SourceAdapter
from archive_sync_engine.adapters.source import SourceRefreshCursor
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.asset_store import AssetStore
from archive_sync_engine.importer.progress import ImportProgress
from archive_sync_engine.importer.state import ImportState
from archive_sync_engine.models import CanonicalMessage
from archive_sync_engine.models.ids import MessageId
from archive_sync_engine.rate_limit import OperationRateLimiter


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
        on_refresh_cursor: Callable[[str, SourceRefreshCursor], None] | None = None,
        resume_state: ImportState | None = None,
        incremental_refresh: bool = False,
        rate_limiter: OperationRateLimiter | None = None,
        existing_messages_by_conversation: dict[str, tuple[CanonicalMessage, ...]] | None = None,
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

        rate_limiter = rate_limiter or OperationRateLimiter()
        refresh_cursors: dict[str, SourceRefreshCursor] = {}
        examined_messages = 0

        attachments_downloaded = 0
        attachments_reused = 0
        existing_messages_by_conversation = existing_messages_by_conversation or {}
        imported_message_ids_by_conversation: dict[str, set[str]] = {}
        authoritative_pins_by_conversation: dict[str, set[str]] = {}

        if on_status is not None and incremental_refresh:
            on_status(
                ImportProgress(
                    phase="refresh",
                    mode="incremental",
                    lookback_seconds=source.incremental_refresh_lookback.total_seconds(),
                    traversal="adapter_incremental",
                    detail="incremental source refresh enabled",
                )
            )
        elif on_status is not None:
            on_status(
                ImportProgress(
                    phase="refresh",
                    mode="full",
                    traversal="complete_source_traversal",
                    detail="complete source traversal enabled",
                )
            )
        if resume_state is not None:
            raw_cursors = resume_state.payload.get("refresh_cursors", {})
            if isinstance(raw_cursors, dict):
                refresh_cursors = {
                    str(key): SourceRefreshCursor.from_json_dict(value)
                    for key, value in raw_cursors.items()
                    if isinstance(value, dict)
                }

        #
        # Identities
        #
        # A checkpoint resume skips identities because the original import
        # committed them before reaching message traversal. A completed-run
        # refresh intentionally re-traverses identities so newly discovered
        # authors/reaction participants are incorporated.
        #

        if resume_state is None or incremental_refresh:
            if on_status is not None:
                on_status(ImportProgress(phase="identities", current=0))
            identity_count = 0
            identities = (
                source.iter_identities_since(refresh_cursors)
                if incremental_refresh
                else source.iter_identities()
            )
            for identity in identities:
                # Identity discovery is a reconciliation boundary, not a
                # one-time insert.  A full import can legitimately encounter
                # an identity already persisted by an earlier/partial import
                # (for example after an interrupted run or a source adapter
                # reusing an identity discovered through another traversal).
                # Keep the canonical identity current without allowing a
                # duplicate-key failure to abort the import before message
                # traversal begins.
                writer.upsert_identity(identity)
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
        # Custom emojis
        #
        # Some reactions may reference custom emojis that are not owned by
        # the source guild (Discord permits reactions using emojis from other
        # shared guilds). Identity discovery intentionally precedes this
        # stage because the Discord source adapter uses its cached raw-message
        # traversal to discover reaction-only custom emojis and their assets.
        #
        iter_custom_emojis = getattr(source, "iter_custom_emojis", None)
        if callable(iter_custom_emojis):
            custom_emojis = iter_custom_emojis()
            if isinstance(custom_emojis, Iterable):
                custom_emoji_bytes = getattr(source, "custom_emoji_bytes", None)
                for custom_emoji in custom_emojis:
                    writer.upsert_custom_emoji(custom_emoji)
                    if not asset_store.exists(custom_emoji.sha256):
                        if not callable(custom_emoji_bytes):
                            raise TypeError(
                                "Source adapter yielded custom emoji data without "
                                "providing custom_emoji_bytes()."
                            )
                        asset_store.put(custom_emoji_bytes(custom_emoji))

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

        resume_reached = resume_state is None or incremental_refresh

        raw_conversations = source.iter_conversations()
        conversation_total = (
            len(raw_conversations) if isinstance(raw_conversations, Sized) else None
        )
        conversations = tuple(raw_conversations)
        if on_status is not None:
            on_status(
                ImportProgress(
                    phase="conversations",
                    current=0,
                    total=conversation_total,
                )
            )
        conversation_count = 0
        pin_getter = getattr(source, "iter_pinned_message_ids", None)
        pin_getter_impl = getattr(type(source), "iter_pinned_message_ids", None)
        has_authoritative_pin_getter = callable(pin_getter) and (
            not isinstance(source, SourceAdapter)
            or pin_getter_impl is not SourceAdapter.iter_pinned_message_ids
        )

        for conversation in conversations:

            # The first call establishes the channel pacing clock without
            # sleeping; subsequent conversations are delayed as configured.
            rate_limiter.before_channel()

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
                if incremental_refresh:
                    writer.upsert_conversation(conversation)
                else:
                    writer.add_conversation(conversation)

            # Pin state is channel-scoped mutable state. Snapshot the
            # authoritative source pin collection before traversing the
            # message window so message traversal/caching cannot change the
            # state that this import run is reconciling against. The snapshot
            # is deliberately independent of the incremental cursor.
            if has_authoritative_pin_getter:
                pinned_ids = pin_getter(conversation)
                if pinned_ids is not None and isinstance(pinned_ids, Iterable):
                    authoritative_pins_by_conversation[conversation_id] = {
                        str(message_id) for message_id in pinned_ids
                    }

            skipping_messages = (
                resume_state is not None
                and conversation_id == resume_conversation_id
                and resume_message_id is not None
            )

            cursor = refresh_cursors.get(conversation_id)
            if incremental_refresh and cursor is not None:
                traversal = "adapter_incremental"
                messages = source.iter_messages_since(conversation, cursor)
                if on_status is not None:
                    on_status(
                        ImportProgress(
                            phase="refresh",
                            mode="incremental",
                            cursor=str(cursor.message_id),
                            lookback_seconds=source.incremental_refresh_lookback.total_seconds(),
                            traversal=traversal,
                            detail=conversation_id,
                        )
                    )
            else:
                traversal = "complete_source_traversal"
                messages = source.iter_messages(conversation)
                if on_status is not None and incremental_refresh:
                    on_status(
                        ImportProgress(
                            phase="refresh",
                            mode="incremental",
                            lookback_seconds=source.incremental_refresh_lookback.total_seconds(),
                            traversal="fallback_complete_source_traversal",
                            detail=conversation_id,
                        )
                    )
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

            first_message = True
            for message in messages:

                if skipping_messages:
                    if str(message.id) == str(resume_message_id):
                        skipping_messages = False
                        continue
                    continue

                if not first_message:
                    rate_limiter.before_message()
                first_message = False
                examined_messages += 1

                #
                # Persist the complete canonical message aggregate.
                #
                # ArchiveWriter also persists attachment metadata and
                # message/attachment relationships.
                #

                if incremental_refresh:
                    writer.upsert_message(message)
                else:
                    writer.add_message(message)
                imported_message_ids_by_conversation.setdefault(
                    conversation_id,
                    set(),
                ).add(str(message.id))
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

                    # Attachment content is content-addressed.  During a
                    # refresh, a previously stored SHA-256 never needs to be
                    # downloaded again.  This is the primary protection
                    # against re-downloading the archive's historical media.
                    if not asset_store.exists(attachment.sha256):
                        attachments_downloaded += 1
                        content = source.attachment_bytes(
                            attachment,
                        )

                        asset_store.put_attachment(
                            attachment,
                            content,
                        )
                    else:
                        attachments_reused += 1

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

                refresh_cursors[conversation_id] = SourceRefreshCursor(
                    created_at=message.created_at,
                    message_id=str(message.id),
                )

                if on_progress is not None:

                    # The coordinator commits canonical data and the opaque
                    # checkpoint before the source cursor is advanced. This
                    # ordering prevents an interruption from ever advancing
                    # the source cursor past uncommitted archive data.
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


                if on_refresh_cursor is not None and not has_authoritative_pin_getter:
                    on_refresh_cursor(
                        conversation_id,
                        refresh_cursors[conversation_id],
                    )

        # Reconcile pin state only after message writes have completed.  The
        # source pin collection is authoritative channel metadata; applying it
        # last prevents a stale ``message.pinned`` value from an incremental
        # message window from overwriting the authoritative pin set.  The
        # candidate IDs include both previously archived messages and messages
        # touched during this run, so old pin changes and newly imported
        # messages are handled by the same path.
        current_conversations = {
            str(conversation.id): conversation
            for conversation in conversations
        }
        if has_authoritative_pin_getter:
            for conversation_id, conversation in current_conversations.items():
                pinned_set = authoritative_pins_by_conversation.get(conversation_id)
                if pinned_set is None:
                    # A source may expose the capability dynamically. If its
                    # snapshot was unavailable, take one final authoritative
                    # read rather than silently skipping pin reconciliation.
                    pinned_ids = pin_getter(conversation)
                    if pinned_ids is None or not isinstance(pinned_ids, Iterable):
                        continue
                    pinned_set = {str(message_id) for message_id in pinned_ids}
                # Reconcile against the messages that are actually persisted
                # in this writer transaction.  The coordinator's
                # ``existing_messages_by_conversation`` snapshot is useful for
                # deletion detection, but it is deliberately not the source of
                # truth for pin reconciliation: a refresh can legitimately have
                # an empty/stale snapshot (for example after a prior interrupted
                # session), while the Archive database already contains older
                # messages whose pin state changed.
                persisted_messages = writer.iter_messages_for_conversation(
                    conversation.id,
                )
                candidate_ids = {
                    str(message.id)
                    for message in persisted_messages
                }
                for message_id in sorted(candidate_ids):
                    writer.update_message_pinned(
                        MessageId(message_id),
                        message_id in pinned_set,
                    )
            writer.commit()

        # For adapters with authoritative pin metadata, the refresh cursor is
        # only durable after canonical message data and pin metadata have both
        # been committed.  This prevents a crash between message traversal
        # and pin reconciliation from making the next refresh skip the
        # affected message window.
        if on_refresh_cursor is not None and has_authoritative_pin_getter:
            for conversation_id, cursor in refresh_cursors.items():
                on_refresh_cursor(conversation_id, cursor)

        if incremental_refresh and existing_messages_by_conversation:
            # Cursor-based traversal cannot reveal records deleted before the
            # refresh window.  Perform a complete source traversal solely to
            # detect deletions, while retaining the incremental traversal for
            # actual writes and attachment downloads.
            for conversation_id, existing in existing_messages_by_conversation.items():
                conversation = current_conversations.get(conversation_id)
                if conversation is None:
                    continue
                current_ids = {
                    str(message.id)
                    for message in source.iter_messages(conversation)
                }
                for deleted_id in {str(message.id) for message in existing} - current_ids:
                    writer.delete_message(deleted_id)

        if on_status is not None:
            on_status(
                ImportProgress(
                    phase="refresh",
                    mode="incremental" if incremental_refresh else "full",
                    traversal="completed",
                    examined=examined_messages,
                    attachments_downloaded=attachments_downloaded,
                    attachments_reused=attachments_reused,
                    detail="source refresh complete",
                )
            )
