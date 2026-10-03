from __future__ import annotations

from pathlib import Path

from archive_sync_engine.archive.package import ArchivePackage
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.asset_store import AssetStore


def test_archive_package_owns_asset_store(
    tmp_path: Path,
) -> None:
    paths = ArchivePaths(
        root=tmp_path,
    )

    paths.ensure_exists()

    package = ArchivePackage(
        paths,
    )

    assert isinstance(
        package.asset_store,
        AssetStore,
    )

def test_archive_package_round_trips_full_import_recovery_cursors(
    tmp_path: Path,
) -> None:
    """Full-import recovery cursors persist independently of refresh cursors."""
    from datetime import datetime, timezone

    from archive_sync_engine.adapters.source import SourceRefreshCursor

    paths = ArchivePaths(root=tmp_path)
    paths.ensure_exists()
    package = ArchivePackage(paths)
    cursor = SourceRefreshCursor(
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        message_id="message-001",
    )

    package.save_import_recovery_cursors({"conversation-001": cursor})

    assert package.load_import_recovery_cursors() == {
        "conversation-001": cursor,
    }

    package.clear_import_recovery_cursors()

    try:
        package.load_import_recovery_cursors()
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Recovery cursors should be removed after completion.")
