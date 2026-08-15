from __future__ import annotations

from pathlib import Path

import pytest

from archive_sync_engine.archive import (
    ArchivePackage,
    ArchivePaths,
    validate_archive_package,
)


def test_archive_package_initialize_creates_empty_valid_package(tmp_path: Path) -> None:
    paths = ArchivePaths(tmp_path / "archive")

    package = ArchivePackage.initialize(paths)

    assert package.paths == paths
    assert paths.database.is_file()
    assert paths.manifest.is_file()
    assert paths.attachments.is_dir()

    report = validate_archive_package(paths)
    assert report.valid is True
    assert report.errors == ()
    assert report.conversations_checked == 0
    assert report.identities_checked == 0
    assert report.messages_checked == 0
    assert report.attachments_checked == 0


def test_archive_package_initialize_does_not_overwrite_existing_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "archive"
    root.mkdir()
    marker = root / "marker.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        ArchivePackage.initialize(ArchivePaths(root))

    assert marker.read_text(encoding="utf-8") == "keep"


def test_archive_package_initialize_is_not_allowed_to_reinitialize_package(
    tmp_path: Path,
) -> None:
    paths = ArchivePaths(tmp_path / "archive")
    ArchivePackage.initialize(paths)
    manifest_before = paths.manifest.read_text(encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        ArchivePackage.initialize(paths)

    assert paths.manifest.read_text(encoding="utf-8") == manifest_before
