"""
Canonical import coordinator.

CanonicalImportCoordinator owns the lifecycle of a canonical import
session.

CanonicalImporter performs the actual acquisition and persistence of
canonical entities.

The coordinator is responsible for:

    * creating the import session;
    * persisting session state;
    * invoking CanonicalImporter;
    * persisting importer-owned progress state;
    * marking successful imports as completed; and
    * recording import failures.

Session state is operational metadata and is stored in the Archive
Package separately from canonical archive data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from archive_sync_engine.adapters import SourceAdapter
from archive_sync_engine.adapters.source import SourceRefreshCursor
from archive_sync_engine.archive.package import ArchivePackage
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.importer import (
    DiscoveryPhase,
    DiscoveryState,
    ImportProgress,
    ImportState,
)
from archive_sync_engine.importer.canonical_importer import (
    CanonicalImporter,
)
from archive_sync_engine.models import CanonicalMessage
from archive_sync_engine.rate_limit import OperationRateLimiter
from archive_sync_engine.sync.session import (
    SyncDirection,
    SyncSession,
)


@dataclass(frozen=True, slots=True)
class ImportReport:
    """Summary of one completed canonical import."""

    session_id: str
    identities: int
    conversations: int
    messages: int
    attachments: int


class CanonicalImportCoordinator:
    """
    Coordinates one complete canonical import session.
    """

    def __init__(
        self,
        paths: ArchivePaths,
    ) -> None:
        self._paths = paths
        self._package = ArchivePackage(
            paths,
        )

    def run(
        self,
        source: SourceAdapter,
        *,
        resume: bool = False,
        on_status: Callable[[ImportProgress], None] | None = None,
        between_messages_seconds: float = 0.0,
        between_channels_seconds: float = 0.0,
        discovery_batch_size: int = 100,
    ) -> ImportReport:
        """
        Execute a complete canonical import.

        A new SyncSession is persisted before import begins. If --resume
        targets a completed import, the previous completion is treated as a
        request for an incremental source refresh rather than a checkpoint
        continuation.

        CanonicalImporter reports importer-owned progress through
        save_import_state().

        When import succeeds, the session is marked completed.

        When import fails, the session records the error and the
        original exception is re-raised.
        """

        started_at = datetime.now(
            timezone.utc,
        )

        previous_session = None
        if resume:
            try:
                previous_session = self.load_session()
            except FileNotFoundError:
                previous_session = None

        try:
            previous_discovery_state = self._package.load_discovery_state()
        except FileNotFoundError:
            previous_discovery_state = None

        try:
            previous_recovery_cursors = self._package.load_import_recovery_cursors()
        except FileNotFoundError:
            previous_recovery_cursors = {}
        # A completed run is an explicit refresh request. A failed/interrupted
        # run is a checkpoint continuation, even when source-aware refresh
        # cursors were written before the failure. Treating those cursors as a
        # refresh trigger would discard the full-resume traversal boundary and
        # could force unnecessary source replay.
        incremental_refresh = bool(
            resume
            and previous_session is not None
            and previous_session.completed
        )

        session = SyncSession(
            id=f"import-{uuid4()}",
            direction=SyncDirection.IMPORT,
            started_at=started_at,
            updated_at=started_at,
        )

        self._package.save_session(
            session,
        )
        initial_import_source = self._package.snapshot_import_source_state()
        if initial_import_source is not None:
            self._package.save_last_import_source_state(initial_import_source)

        try:
            if not incremental_refresh and not (resume and previous_discovery_state is not None):
                self._package.save_discovery_state(DiscoveryState.identities_started())
            existing_messages_by_conversation: dict[str, tuple[CanonicalMessage, ...]] = {}
            if incremental_refresh and previous_session is not None and previous_session.completed:
                from archive_sync_engine.archive import Archive

                with Archive(self._paths) as existing_archive:
                    existing_messages_by_conversation = {
                        str(conversation.id): tuple(
                            existing_archive.iter_messages_for_conversation(conversation.id)
                        )
                        for conversation in existing_archive.iter_conversations()
                    }

            resume_state = None
            if resume and not incremental_refresh:
                try:
                    resume_state = self.load_import_state()
                except FileNotFoundError:
                    # Discovery checkpoints are independently resumable. No
                    # message checkpoint exists until canonical traversal has
                    # actually begun, so an identity-phase failure resumes
                    # from discovery-state.json without inventing a message
                    # cursor.
                    if previous_discovery_state is None or previous_discovery_state.phase not in {
                        DiscoveryPhase.IDENTITIES,
                        DiscoveryPhase.CANONICAL,
                    }:
                        raise
            elif resume and incremental_refresh:
                try:
                    cursors = self._package.load_import_cursors()
                except FileNotFoundError:
                    # Archives created before source-aware cursors were
                    # introduced remain safe: the first refresh falls back
                    # to the adapter's complete traversal.
                    cursors = {}
                resume_state = ImportState(
                    payload={
                        "refresh_cursors": {
                            key: cursor.to_json_dict()
                            for key, cursor in cursors.items()
                        },
                    },
                )

            resume_discovery_state = (
                previous_discovery_state
                if resume and not incremental_refresh
                else None
            )

            with ArchiveWriter(
                self._paths,
            ) as writer:

                refresh_cursors: dict[str, "SourceRefreshCursor"] = {}
                if resume_state is not None:
                    raw_cursors = resume_state.payload.get("refresh_cursors", {})
                    if isinstance(raw_cursors, dict):
                        from archive_sync_engine.adapters.source import SourceRefreshCursor

                        refresh_cursors = {
                            str(key): SourceRefreshCursor.from_json_dict(value)
                            for key, value in raw_cursors.items()
                            if isinstance(value, dict)
                        }

                def checkpoint(state: ImportState) -> None:
                    writer.commit()
                    self.save_import_state(state)

                def save_refresh_cursor(
                    conversation_id: str,
                    cursor: "SourceRefreshCursor",
                ) -> None:
                    refresh_cursors[conversation_id] = cursor
                    self._package.save_import_cursors(refresh_cursors)

                def save_recovery_cursor(
                    conversation_id: str,
                    cursor: "SourceRefreshCursor",
                ) -> None:
                    previous_recovery_cursors[conversation_id] = cursor
                    self._package.save_import_recovery_cursors(previous_recovery_cursors)

                def checkpoint_discovery(state: DiscoveryState) -> None:
                    # Discovery state is advanced only after the canonical
                    # records in the batch have been committed. If state
                    # persistence itself fails, the committed records remain
                    # safely replayable on the next run.
                    writer.commit()
                    self._package.save_discovery_state(state)

                importer = CanonicalImporter()
                rate_limiter = OperationRateLimiter(
                    between_messages_seconds=between_messages_seconds,
                    between_channels_seconds=between_channels_seconds,
                )

                # Keep the coordinator invocation aligned with the public
                # CanonicalImporter.import_source contract. Coordinator-only
                # reconciliation data must not be passed here unless the
                # importer explicitly accepts and implements it.
                importer.import_source(
                    source=source,
                    writer=writer,
                    asset_store=self._package.asset_store,
                    on_progress=checkpoint,
                    on_status=on_status,
                    on_refresh_cursor=save_refresh_cursor,
                    on_recovery_cursor=save_recovery_cursor,
                    on_discovery_checkpoint=checkpoint_discovery,
                    resume_state=resume_state,
                    resume_discovery_state=resume_discovery_state,
                    resume_message_cursor=(
                        previous_recovery_cursors.get(
                            str(resume_state.payload.get("conversation_id"))
                        )
                        if resume_state is not None and not incremental_refresh
                        else None
                    ),
                    incremental_refresh=incremental_refresh,
                    discovery_batch_size=discovery_batch_size,
                    rate_limiter=rate_limiter,
                    **({
                        "existing_messages_by_conversation": existing_messages_by_conversation,
                    } if existing_messages_by_conversation else {}),
                )

                unresolved_reply_targets = importer.reconcile_missing_reply_targets(
                    source=source,
                    writer=writer,
                    asset_store=self._package.asset_store,
                    on_status=on_status,
                    rate_limiter=rate_limiter,
                )
                if unresolved_reply_targets:
                    missing = ", ".join(unresolved_reply_targets)
                    raise RuntimeError(
                        "Canonical import cannot be marked complete because "
                        "the following reply targets could not be recovered from "
                        f"the source: {missing}."
                    )

            # The writer context has committed the final canonical import
            # boundary. Only now can discovery be marked complete.
            completed_discovery_state = self._package.load_discovery_state()
            self._package.save_discovery_state(
                completed_discovery_state.with_phase(DiscoveryPhase.COMPLETED)
            )
            self._package.clear_import_recovery_cursors()

            finished_at = datetime.now(
                timezone.utc,
            )

            session.updated_at = finished_at
            session.completed = True

            self._package.save_session(
                session,
            )
            completed_import_source = self._package.snapshot_import_source_state()
            if completed_import_source is not None:
                self._package.save_last_import_source_state(completed_import_source)

            from archive_sync_engine.archive import Archive

            with Archive(self._paths) as archive:
                return ImportReport(
                    session_id=session.id,
                    identities=sum(1 for _ in archive.iter_identities()),
                    conversations=sum(1 for _ in archive.iter_conversations()),
                    messages=sum(1 for _ in archive.iter_messages()),
                    attachments=sum(1 for _ in archive.iter_attachments()),
                )

        except Exception as exc:

            failed_at = datetime.now(
                timezone.utc,
            )

            session.updated_at = failed_at
            session.error = str(exc)

            self._package.save_session(
                session,
            )
            failed_import_source = self._package.snapshot_import_source_state()
            if failed_import_source is not None:
                self._package.save_last_import_source_state(failed_import_source)

            raise

    def load_import_state(
        self,
    ) -> ImportState:
        """
        Load the persisted importer-owned state.
        """

        return self._package.load_import_state()

    def load_session(
        self,
    ) -> SyncSession:
        """
        Load the persisted import session from the Archive Package.
        """

        return self._package.load_session()

    def save_import_state(
        self,
        state: ImportState,
    ) -> None:
        """
        Persist importer-owned state.

        The coordinator does not inspect or modify the state payload.
        """

        self._package.save_import_state(
            state,
        )

    def load_import_cursors(self):
        """Load persisted source-aware incremental refresh cursors."""
        return self._package.load_import_cursors()
