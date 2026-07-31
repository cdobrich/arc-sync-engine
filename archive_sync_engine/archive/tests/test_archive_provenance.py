from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

from archive_sync_engine.archive import Archive
from archive_sync_engine.archive.manifest import ArchiveManifest
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.models.provenance import (
    CanonicalEndpoint,
    CanonicalProvenance,
    CanonicalTransfer,
)


def test_archive_exposes_provenance(
    tmp_path: Path,
) -> None:
    """
    Archive exposes the complete persisted provenance history
    through its public provenance property.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    manifest = ArchiveManifest(
        archive_format_version=1,
        archive_engine_version="test",
        created_at=datetime(
            2026,
            7,
            30,
            17,
            0,
            tzinfo=timezone.utc,
        ),
    )

    paths.manifest.write_text(
        json.dumps(
            manifest.to_json_dict(),
            indent=2,
        ),
        encoding="utf-8",
    )

    source = CanonicalEndpoint(
        adapter="discord",
        identifier="discord-server-123",
        name="Original Discord Server",
    )

    destination = CanonicalEndpoint(
        adapter="fluxer",
        identifier="fluxer-server-456",
        name="Primary Fluxer Server",
    )

    provenance = CanonicalProvenance(
        history=(
            CanonicalTransfer(
                source=source,
                destination=destination,
                started_at=datetime(
                    2026,
                    7,
                    30,
                    18,
                    0,
                    tzinfo=timezone.utc,
                ),
                finished_at=datetime(
                    2026,
                    7,
                    30,
                    18,
                    30,
                    tzinfo=timezone.utc,
                ),
                imported_messages=1000,
                exported_messages=1000,
            ),
            CanonicalTransfer(
                source=destination,
                destination=None,
                started_at=datetime(
                    2026,
                    7,
                    31,
                    9,
                    0,
                    tzinfo=timezone.utc,
                ),
                imported_messages=250,
                exported_messages=0,
            ),
        ),
    )

    writer = ArchiveWriter(
        paths,
    )

    try:
        writer.write_provenance(
            provenance,
        )

        writer.commit()

    finally:
        writer.close()

    with Archive(
        paths,
    ) as archive:

        assert archive.provenance == provenance