from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from archive_sync_engine.archive.package import ArchivePackage
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.sync.session import (
    SyncDirection,
    SyncSession,
)


def test_archive_package_session_round_trip(
    tmp_path: Path,
) -> None:
    paths = ArchivePaths(
        root=tmp_path,
    )

    paths.ensure_exists()

    package = ArchivePackage(
        paths,
    )

    session = SyncSession(
        id="session-import-001",
        direction=SyncDirection.IMPORT,
        started_at=datetime(
            2026,
            7,
            30,
            18,
            0,
            tzinfo=timezone.utc,
        ),
        updated_at=datetime(
            2026,
            7,
            30,
            18,
            15,
            tzinfo=timezone.utc,
        ),
        paused=True,
        checkpoint="source-cursor-123",
    )

    package.save_session(
        session,
    )

    restored = package.load_session()

    assert restored == session


def test_archive_package_session_file_is_created(
    tmp_path: Path,
) -> None:
    paths = ArchivePaths(
        root=tmp_path,
    )

    paths.ensure_exists()

    package = ArchivePackage(
        paths,
    )

    session = SyncSession(
        id="session-export-001",
        direction=SyncDirection.EXPORT,
        started_at=datetime(
            2026,
            7,
            30,
            19,
            0,
            tzinfo=timezone.utc,
        ),
        updated_at=datetime(
            2026,
            7,
            30,
            19,
            30,
            tzinfo=timezone.utc,
        ),
        completed=True,
        checkpoint="message-987",
    )

    package.save_session(
        session,
    )

    assert paths.session.exists()


def test_archive_package_persists_generic_run_configuration(tmp_path) -> None:
    from archive_sync_engine.archive.package import ArchivePackage
    from archive_sync_engine.archive.paths import ArchivePaths
    from archive_sync_engine.sync.run_configuration import (
        RunDirection,
        SyncRunConfiguration,
    )

    package = ArchivePackage(ArchivePaths(tmp_path))
    configuration = SyncRunConfiguration(
        direction=RunDirection.IMPORT,
        input_adapter="fluxer",
        input_scope=("1375567890027713164",),
    )

    package.save_run_configuration(configuration)

    assert package.load_run_configuration() == configuration
