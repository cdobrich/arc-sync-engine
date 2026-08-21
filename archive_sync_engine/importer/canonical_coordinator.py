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
from archive_sync_engine.importer import ImportProgress, ImportState
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

        cursor_state_available = self._paths.import_cursors.is_file()
        incremental_refresh = bool(
            resume
            and previous_session is not None
            and (previous_session.completed or cursor_state_available)
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

        try:
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
                resume_state = self.load_import_state()
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
                    resume_state=resume_state,
                    incremental_refresh=incremental_refresh,
                    rate_limiter=rate_limiter,
                    **({
                        "existing_messages_by_conversation": existing_messages_by_conversation,
                    } if existing_messages_by_conversation else {}),
                )

            finished_at = datetime.now(
                timezone.utc,
            )

            session.updated_at = finished_at
            session.completed = True

            self._package.save_session(
                session,
            )

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
