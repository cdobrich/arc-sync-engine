from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from archive_sync_engine.archive.package import ArchivePackage
from archive_sync_engine.archive.paths import ArchivePaths


def test_archive_package_exposes_asset_store(
    tmp_path: Path,
) -> None:
    paths = ArchivePaths(
        root=tmp_path,
    )

    paths.ensure_exists()

    package = ArchivePackage(
        paths,
    )

    content = b"package-owned attachment"

    digest = package.asset_store.put(
        content,
    )

    expected = sha256(
        content,
    ).hexdigest()

    assert digest == expected

    assert package.asset_store.get(
        expected,
    ) == content


def test_archive_package_asset_store_uses_package_root(
    tmp_path: Path,
) -> None:
    paths = ArchivePaths(
        root=tmp_path,
    )

    paths.ensure_exists()

    package = ArchivePackage(
        paths,
    )

    content = b"archive package asset"

    digest = package.asset_store.put(
        content,
    )

    assert package.asset_store.path_for_sha256(
        digest,
    ).is_file()

    assert package.asset_store.path_for_sha256(
        digest,
    ).is_relative_to(
        tmp_path,
    )