from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.models.provenance import (
    CanonicalEndpoint,
    CanonicalProvenance,
    CanonicalTransfer,
)


def test_writer_persists_provenance(
    tmp_path: Path,
) -> None:
    """
    ArchiveWriter persists every transfer in a CanonicalProvenance
    history.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    source = CanonicalEndpoint(
        adapter="discord",
        identifier="discord-server-123",
        name="Discord Server",
    )

    destination = CanonicalEndpoint(
        adapter="fluxer",
        identifier="fluxer-server-456",
        name="Fluxer Server",
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
                imported_messages=100,
                exported_messages=100,
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
                imported_messages=25,
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

    from archive_sync_engine.archive.store import ArchiveStore

    store = ArchiveStore.open(
        paths,
    )

    try:
        transfers = tuple(
            store.iter_provenance_transfers()
        )

        assert transfers == provenance.history

    finally:
        store.close()
