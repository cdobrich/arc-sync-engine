from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.recomposer import ArchiveRecomposer
from archive_sync_engine.archive.store import ArchiveStore
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.models.provenance import (
    CanonicalEndpoint,
    CanonicalProvenance,
    CanonicalTransfer,
)


def test_recomposer_reconstructs_complete_provenance(
    tmp_path: Path,
) -> None:
    """
    ArchiveRecomposer reconstructs the complete canonical
    provenance history from persistent storage.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    source = CanonicalEndpoint(
        adapter="discord",
        identifier="discord-server-123",
        name="Discord Server",
    )

    fluxer = CanonicalEndpoint(
        adapter="fluxer",
        identifier="fluxer-server-456",
        name="Fluxer Server",
    )

    slack = CanonicalEndpoint(
        adapter="slack",
        identifier="slack-workspace-789",
        name="Slack Workspace",
    )

    provenance = CanonicalProvenance(
        history=(
            CanonicalTransfer(
                source=source,
                destination=fluxer,
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
                source=fluxer,
                destination=slack,
                started_at=datetime(
                    2026,
                    7,
                    31,
                    9,
                    0,
                    tzinfo=timezone.utc,
                ),
                finished_at=None,
                imported_messages=250,
                exported_messages=200,
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

    store = ArchiveStore.open(
        paths,
    )

    try:
        recomposer = ArchiveRecomposer(
            store,
        )

        reconstructed = recomposer.recompose_provenance()

        assert reconstructed == provenance

    finally:
        store.close()