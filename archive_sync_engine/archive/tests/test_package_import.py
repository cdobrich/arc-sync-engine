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