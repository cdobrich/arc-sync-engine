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

from archive_sync_engine.adapters import IdentityDiscoveryBatch, SourceAdapter
from archive_sync_engine.adapters.source import SourceRefreshCursor
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.asset_store import AssetStore
from archive_sync_engine.importer.progress import ImportProgress
from archive_sync_engine.importer.state import ImportState
from archive_sync_engine.importer.traversal import ImportTraversalMode
from archive_sync_engine.importer.discovery_state import DiscoveryPhase, DiscoveryState
from archive_sync_engine.models import CanonicalIdentity, CanonicalMessage
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
        on_recovery_cursor: Callable[[str, SourceRefreshCursor], None] | None = None,
        on_discovery_checkpoint: Callable[[DiscoveryState], None] | None = None,
        resume_state: ImportState | None = None,
        resume_discovery_state: DiscoveryState | None = None,
        resume_message_cursor: SourceRefreshCursor | None = None,
        incremental_refresh: bool = False,
        discovery_batch_size: int = 100,
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

        if discovery_batch_size <= 0:
            raise ValueError("Discovery batch size must be greater than zero.")

        if resume_state is not None and not incremental_refresh:
            traversal_mode = resume_state.payload.get("traversal_mode")
            if traversal_mode not in (None, ImportTraversalMode.FULL.value):
                raise ValueError(
                    "An interrupted import checkpoint cannot be resumed through "
                    f"the {traversal_mode!r} traversal mode."
                )

        rate_limiter = rate_limiter or OperationRateLimiter()
        refresh_cursors: dict[str, SourceRefreshCursor] = {}
        examined_messages = 0

        attachments_downloaded = 0
        attachments_reused = 0
        existing_messages_by_conversation = existing_messages_by_conversation or {}
        # Identity discovery is a logical-record operation, not an
        # observation-count operation.  A source may encounter the same
        # participant in guild membership, message authorship, and reactions
        # many times.  Seed the set from the durable archive so a resumed
        # traversal cannot count an already-committed identity again.
        committed_identity_keys = {
            str(identity.identity_key)
            for identity in writer.iter_identities()
        }
        identity_count = len(committed_identity_keys)
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

        resume_after_identity_discovery = (
            resume_discovery_state is not None
            and not incremental_refresh
            and resume_discovery_state.phase is DiscoveryPhase.CANONICAL
        )
        if (resume_state is None or incremental_refresh) and not resume_after_identity_discovery:
            if on_status is not None:
                on_status(ImportProgress(phase="identities", current=0))
            identity_count = len(committed_identity_keys)
            discovery_state = DiscoveryState(
                phase=DiscoveryPhase.IDENTITIES,
                records_committed=identity_count,
                updated_at=DiscoveryState.identities_started().updated_at,
            )

            if incremental_refresh:
                identities = source.iter_identities_since(refresh_cursors)
                batch: list[CanonicalIdentity] = []
                for identity in identities:
                    batch.append(identity)
                    if len(batch) >= discovery_batch_size:
                        last_new_key = discovery_state.last_record_key
                        for item in batch:
                            writer.upsert_identity(item)
                            key = str(item.identity_key)
                            if key not in committed_identity_keys:
                                committed_identity_keys.add(key)
                                identity_count += 1
                                last_new_key = key
                        if on_discovery_checkpoint is not None:
                            discovery_state = discovery_state.advance_batch(
                                records_committed=identity_count,
                                last_record_key=last_new_key,
                            )
                            on_discovery_checkpoint(discovery_state)
                        batch = []
                if batch or identity_count == 0:
                    last_new_key = discovery_state.last_record_key
                    for item in batch:
                        writer.upsert_identity(item)
                        key = str(item.identity_key)
                        if key not in committed_identity_keys:
                            committed_identity_keys.add(key)
                            identity_count += 1
                            last_new_key = key
                    if on_discovery_checkpoint is not None:
                        discovery_state = discovery_state.advance_batch(
                            records_committed=identity_count,
                            last_record_key=last_new_key,
                        )
                        on_discovery_checkpoint(discovery_state)
            else:
                resume_cursor: dict[str, object] | None = None
                if resume_discovery_state is not None:
                    metadata = dict(resume_discovery_state.metadata)
                    adapter_name = metadata.get("adapter")
                    if adapter_name is not None and str(adapter_name) != source.name:
                        raise ValueError(
                            "Persisted identity discovery cursor belongs to "
                            f"adapter {adapter_name!r}, not {source.name!r}."
                        )
                    raw_cursor = metadata.get("cursor")
                    if isinstance(raw_cursor, dict):
                        resume_cursor = dict(raw_cursor)
                    discovery_state = resume_discovery_state
                    identity_count = discovery_state.records_committed
                    if on_status is not None and resume_cursor:
                        on_status(
                            ImportProgress(
                                phase="identity_scan",
                                current=0,
                                detail=(
                                    "Resuming identity discovery from checkpoint: "
                                    f"{discovery_state.records_committed} identities committed; "
                                    f"cursor={resume_cursor}"
                                ),
                            )
                        )

                batch_iterator = getattr(source, "iter_identity_batches", None)
                if callable(batch_iterator):
                    candidate_batches = batch_iterator(
                        resume_cursor=resume_cursor,
                        batch_size=discovery_batch_size,
                    )
                    try:
                        iter(candidate_batches)
                    except TypeError:
                        # Duck-typed test doubles and pre-VS202 source objects
                        # may expose the new name without implementing it.
                        candidate_batches = SourceAdapter.iter_identity_batches.__get__(source)(
                            resume_cursor=resume_cursor,
                            batch_size=discovery_batch_size,
                        )
                else:
                    candidate_batches = SourceAdapter.iter_identity_batches.__get__(source)(
                        resume_cursor=resume_cursor,
                        batch_size=discovery_batch_size,
                    )
                for discovery_batch in candidate_batches:
                    if not isinstance(discovery_batch, IdentityDiscoveryBatch):
                        raise TypeError(
                            "Source adapter identity discovery must yield "
                            "IdentityDiscoveryBatch instances."
                        )
                    last_new_key = discovery_state.last_record_key
                    for identity in discovery_batch.identities:
                        writer.upsert_identity(identity)
                        key = str(identity.identity_key)
                        if key in committed_identity_keys:
                            continue
                        committed_identity_keys.add(key)
                        identity_count += 1
                        last_new_key = key
                        if on_status is not None:
                            on_status(
                                ImportProgress(
                                    phase="identities",
                                    current=identity_count,
                                    detail=key,
                                )
                            )

                    cursor_metadata = {
                        "adapter": source.name,
                        "cursor": dict(discovery_batch.cursor),
                    }
                    if on_discovery_checkpoint is not None:
                        last_key = last_new_key
                        discovery_state = discovery_state.advance_batch(
                            records_committed=identity_count,
                            last_record_key=last_key,
                            metadata=cursor_metadata,
                        )
                        on_discovery_checkpoint(discovery_state)

                    if discovery_batch.complete:
                        break

        if on_discovery_checkpoint is not None:
            current_state = (
                resume_discovery_state
                if resume_after_identity_discovery and resume_discovery_state is not None
                else DiscoveryState(
                    phase=DiscoveryPhase.CANONICAL,
                    batch_number=(
                        discovery_state.batch_number
                        if 'discovery_state' in locals()
                        else 0
                    ),
                    records_committed=(
                        discovery_state.records_committed
                        if 'discovery_state' in locals()
                        else 0
                    ),
                    last_record_key=(
                        discovery_state.last_record_key
                        if 'discovery_state' in locals()
                        else None
                    ),
                )
            )
            on_discovery_checkpoint(current_state.with_phase(DiscoveryPhase.CANONICAL))

        # Materialize the source conversation boundary before persisting
        # custom emojis or message data. A full import must not attempt to
        # recreate a canonical conversation that is already present in the
        # Archive. Keep identity traversal first so existing failure ordering
        # and source-adapter lifecycle semantics remain unchanged.
        conversations = tuple(source.iter_conversations())
        conversation_total = len(conversations)

        if not incremental_refresh and resume_state is None:
            conversation_ids = tuple(str(conversation.id) for conversation in conversations)
            conversation_id_counts: dict[str, int] = {}
            for conversation_id in conversation_ids:
                conversation_id_counts[conversation_id] = conversation_id_counts.get(
                    conversation_id,
                    0,
                ) + 1
            duplicate_ids = tuple(
                conversation_id
                for conversation_id in dict.fromkeys(conversation_ids)
                if conversation_id_counts[conversation_id] > 1
            )
            if duplicate_ids:
                preview = ", ".join(duplicate_ids[:5])
                if len(duplicate_ids) > 5:
                    preview += f", ... (+{len(duplicate_ids) - 5} more)"
                raise ValueError(
                    "Import preflight detected duplicate canonical conversation IDs "
                    f"from the source: {preview}. The source traversal must yield "
                    "each canonical conversation only once."
                )

            existing_ids = writer.existing_conversation_ids(conversation_ids)
            existing_conversation_ids = tuple(
                conversation_id
                for conversation_id in conversation_ids
                if conversation_id in existing_ids
            )
            if existing_conversation_ids:
                preview = ", ".join(existing_conversation_ids[:5])
                if len(existing_conversation_ids) > 5:
                    preview += f", ... (+{len(existing_conversation_ids) - 5} more)"
                raise ValueError(
                    "Import preflight detected existing Archive conversations: "
                    f"{preview}. A full import cannot recreate conversations already "
                    "present in the Archive. If this is an existing Archive that you "
                    "want to refresh, rerun with --resume."
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

        resume_reached = resume_state is None or incremental_refresh

        if on_status is not None:
            on_status(
                ImportProgress(
                    phase="conversations",
                    current=0,
                    total=conversation_total,
                    completed=0,
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
            conversation_detail = str(
                getattr(conversation, "title", None) or conversation.id
            )

            resume_conversation = False
            if resume_state is not None and not resume_reached:
                if conversation_id == resume_conversation_id:
                    resume_reached = True
                    resume_conversation = True
                else:
                    # Conversations before the checkpoint were already
                    # completed by the interrupted run. They are not being
                    # processed again during this resume operation.
                    continue

            if on_status is not None:
                on_status(
                    ImportProgress(
                        phase="conversations",
                        current=conversation_count,
                        total=conversation_total,
                        completed=conversation_count - 1,
                        detail=conversation_detail,
                    )
                )

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
            full_resume_cursor = None
            if (
                resume_state is not None
                and not incremental_refresh
                and conversation_id == resume_conversation_id
                and resume_message_id is not None
            ):
                full_resume_cursor = resume_message_cursor

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
            elif full_resume_cursor is not None:
                traversal = "adapter_resume_after_checkpoint"
                message_iterator_impl = getattr(type(source), "iter_messages_after_checkpoint", None)
                if (
                    message_iterator_impl is not None
                    and message_iterator_impl is not SourceAdapter.iter_messages_after_checkpoint
                ):
                    messages = source.iter_messages_after_checkpoint(
                        conversation,
                        full_resume_cursor,
                    )
                    skipping_messages = False
                else:
                    traversal = "complete_source_traversal_resume_fallback"
                    messages = source.iter_messages(conversation)
                if on_status is not None:
                    on_status(
                        ImportProgress(
                            phase="resume",
                            mode="full",
                            cursor=str(full_resume_cursor.message_id),
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

                # Discover rich identities while the canonical message traversal
                # is already visiting this message.  This eliminates a separate
                # historical scan whose only purpose was identity discovery.
                iter_message_identities = getattr(source, "iter_message_identities", None)
                iter_message_identities_impl = getattr(
                    type(source),
                    "iter_message_identities",
                    None,
                )
                supports_message_identity_hook = callable(iter_message_identities) and (
                    not isinstance(source, SourceAdapter)
                    or iter_message_identities_impl is not None
                    and iter_message_identities_impl is not SourceAdapter.iter_message_identities
                )
                if supports_message_identity_hook:
                    for identity in iter_message_identities(message):
                        writer.upsert_identity(identity)
                        key = str(identity.identity_key)
                        if key in committed_identity_keys:
                            continue
                        committed_identity_keys.add(key)
                        identity_count += 1
                        if on_status is not None:
                            on_status(
                                ImportProgress(
                                    phase="identities",
                                    current=identity_count,
                                    detail=key,
                                )
                            )

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

                    release_attachment_bytes = getattr(
                        source,
                        "release_attachment_bytes",
                        None,
                    )
                    if callable(release_attachment_bytes):
                        release_attachment_bytes(attachment)

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
                    progress_state = ImportState(
                        payload={
                            "conversation_id": str(conversation.id),
                            "message_id": str(message.id),
                            "traversal_mode": ImportTraversalMode.FULL.value,
                        },
                    )
                    on_progress(progress_state)
                    if on_recovery_cursor is not None:
                        on_recovery_cursor(
                            conversation_id,
                            refresh_cursors[conversation_id],
                        )


                if on_refresh_cursor is not None and not has_authoritative_pin_getter:
                    on_refresh_cursor(
                        conversation_id,
                        refresh_cursors[conversation_id],
                    )

            if on_status is not None:
                on_status(
                    ImportProgress(
                        phase="conversations",
                        current=conversation_count,
                        total=conversation_total,
                        completed=conversation_count,
                        detail=conversation_detail,
                    )
                )

        #
        # Custom emojis
        #
        # Run emoji discovery after message traversal. Discord can discover
        # reaction-only custom emojis from the raw messages cached by that
        # traversal, without forcing an earlier historical scan.
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


    def reconcile_missing_reply_targets(
        self,
        source: SourceAdapter,
        writer: ArchiveWriter,
        asset_store: AssetStore,
        *,
        on_status: Callable[[ImportProgress], None] | None = None,
        rate_limiter: OperationRateLimiter | None = None,
    ) -> tuple[str, ...]:
        """Recover source messages needed to satisfy archived reply links.

        An interrupted import can commit a replying message before its target
        is encountered.  Full-import resume normally reaches the target, but
        the target can also lie before the persisted resume cursor.  In that
        case the ordinary resume traversal cannot repair the reference.

        This recovery pass is intentionally demand-driven: it performs no
        source traversal when all reply targets are already present.  When
        targets are missing, it scans the source conversations for just those
        message IDs and persists matching canonical messages.  Newly recovered
        messages can themselves contain a reply to another missing message,
        so the pass repeats until the dependency set reaches a fixed point or
        no additional target can be found.
        """
        persisted_messages = tuple(writer.iter_messages())
        persisted_ids = {str(message.id) for message in persisted_messages}
        pending = {
            str(message.reply_to)
            for message in persisted_messages
            if message.reply_to is not None
            and str(message.reply_to) not in persisted_ids
        }
        if not pending:
            return ()

        conversations = tuple(writer.iter_conversations())
        resolved = 0

        while pending:
            pending_before = set(pending)
            for conversation in conversations:
                if not pending:
                    break

                # Recovery is a point-lookup workload: asking the source for
                # only pending target IDs avoids a second full-history pass
                # (and avoids re-downloading attachments from unrelated messages).
                for message in source.iter_messages_by_ids(conversation, pending):
                    message_id = str(message.id)
                    if message_id not in pending:
                        continue

                    if rate_limiter is not None:
                        rate_limiter.before_message()

                    self._persist_recovery_message(
                        source=source,
                        writer=writer,
                        asset_store=asset_store,
                        message=message,
                    )
                    persisted_ids.add(message_id)
                    pending.discard(message_id)
                    resolved += 1

                    if message.reply_to is not None:
                        reply_target = str(message.reply_to)
                        if reply_target not in persisted_ids:
                            pending.add(reply_target)

                    if on_status is not None:
                        on_status(
                            ImportProgress(
                                phase="reply_recovery",
                                current=resolved,
                                total=resolved + len(pending),
                                detail=message_id,
                            )
                        )

            if pending == pending_before:
                break

        writer.commit()
        return tuple(sorted(pending))

    @staticmethod
    def _persist_recovery_message(
        *,
        source: SourceAdapter,
        writer: ArchiveWriter,
        asset_store: AssetStore,
        message: CanonicalMessage,
    ) -> None:
        """Persist one recovered reply-target message and its dependencies."""
        iter_message_identities = getattr(source, "iter_message_identities", None)
        iter_message_identities_impl = getattr(
            type(source),
            "iter_message_identities",
            None,
        )
        supports_message_identity_hook = callable(iter_message_identities) and (
            not isinstance(source, SourceAdapter)
            or iter_message_identities_impl is not None
            and iter_message_identities_impl is not SourceAdapter.iter_message_identities
        )
        if supports_message_identity_hook:
            for identity in iter_message_identities(message):
                writer.upsert_identity(identity)

        writer.upsert_message(message)
        for attachment in message.attachments:
            if not asset_store.exists(attachment.sha256):
                asset_store.put_attachment(
                    attachment,
                    source.attachment_bytes(attachment),
                )
