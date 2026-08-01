from __future__ import annotations

from pathlib import Path

import pytest

from archive_sync_engine.archive.package import ArchivePackage
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.importer.state import ImportState


def test_archive_package_import_state_round_trip(
    tmp_path: Path,
) -> None:
    """
    ArchivePackage preserves opaque importer-owned state.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    paths.ensure_exists()

    package = ArchivePackage(
        paths,
    )

    state = ImportState(
        payload={
            "cursor": "source-cursor-123",
            "conversation": "conversation-456",
            "message": "message-789",
            "attempt": 3,
        },
    )

    package.save_import_state(
        state,
    )

    restored = package.load_import_state()

    assert restored == state

def test_archive_package_import_state_file_is_created(
    tmp_path: Path,
) -> None:
    """
    Saving import state creates the package import-state file.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    paths.ensure_exists()

    package = ArchivePackage(
        paths,
    )

    package.save_import_state(
        ImportState(
            payload={
                "cursor": "cursor-001",
            },
        ),
    )

    assert paths.import_state.exists()

def test_archive_package_load_import_state_requires_existing_file(
    tmp_path: Path,
) -> None:
    """
    Loading import state fails explicitly when no state exists.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    paths.ensure_exists()

    package = ArchivePackage(
        paths,
    )

    with pytest.raises(
        FileNotFoundError,
    ):
        package.load_import_state()