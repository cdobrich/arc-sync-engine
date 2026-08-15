from __future__ import annotations

import hashlib
import json
from pathlib import Path

from archive_sync_engine.archive import (
    ArchivePaths,
    ArchiveWriter,
    validate_archive_package,
)
from archive_sync_engine.models import CanonicalAttachment
from archive_sync_engine.models.ids import AttachmentId


def _valid_package(tmp_path: Path) -> ArchivePaths:
    paths = ArchivePaths(tmp_path)
    content = b"archive-integrity"
    sha256 = hashlib.sha256(content).hexdigest()
    attachment = CanonicalAttachment(
        id=AttachmentId("attachment-001"),
        filename="example.txt",
        content_type="text/plain",
        size=len(content),
        sha256=sha256,
    )
    with ArchiveWriter(paths) as writer:
        writer.add_attachment(attachment)
        writer._package.asset_store.put_attachment(attachment, content)
    return paths


def test_validate_archive_package_accepts_valid_package(tmp_path: Path) -> None:
    paths = _valid_package(tmp_path)

    report = validate_archive_package(paths)

    assert report.valid is True
    assert report.errors == ()
    assert report.attachments_checked == 1
    assert report.manifest_loaded is True


def test_validate_archive_package_reports_missing_attachment_content(tmp_path: Path) -> None:
    paths = _valid_package(tmp_path)
    attachment_files = list((tmp_path / "assets").rglob("*"))
    for path in attachment_files:
        if path.is_file():
            path.unlink()

    report = validate_archive_package(paths)

    assert report.valid is False
    assert any("missing content" in error for error in report.errors)


def test_validate_cli_returns_nonzero_for_unsupported_manifest_hash_algorithm(tmp_path: Path) -> None:
    from archive_sync_engine.cli import main

    paths = _valid_package(tmp_path)
    manifest = paths.manifest
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["hash_algorithm"] = "md5"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    assert main(["validate", "--archive", str(tmp_path)]) == 1
