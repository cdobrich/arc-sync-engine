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
from datetime import datetime, timezone
from uuid import uuid4

from archive_sync_engine.adapters import SourceAdapter
from archive_sync_engine.archive.package import ArchivePackage
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.importer import ImportState
from archive_sync_engine.importer.canonical_importer import (
    CanonicalImporter,
)
from archive_sync_engine.sync.session import (
    SyncDirection,
    SyncSession,
)


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
    ) -> None:
        """
        Execute a complete canonical import.

        A new SyncSession is persisted before import begins.

        CanonicalImporter reports importer-owned progress through
        save_import_state().

        When import succeeds, the session is marked completed.

        When import fails, the session records the error and the
        original exception is re-raised.
        """

        started_at = datetime.now(
            timezone.utc,
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
            resume_state = None
            if resume:
                resume_state = self.load_import_state()

            with ArchiveWriter(
                self._paths,
            ) as writer:

                def checkpoint(state: ImportState) -> None:
                    writer.commit()
                    self.save_import_state(state)

                importer = CanonicalImporter()

                importer.import_source(
                    source=source,
                    writer=writer,
                    asset_store=self._package.asset_store,
                    on_progress=checkpoint,
                    resume_state=resume_state,
                )

            finished_at = datetime.now(
                timezone.utc,
            )

            session.updated_at = finished_at
            session.completed = True

            self._package.save_session(
                session,
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