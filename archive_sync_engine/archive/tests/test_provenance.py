from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.schema import ArchiveSchema
from archive_sync_engine.archive.store import ArchiveStore
from archive_sync_engine.models.provenance import (
    CanonicalEndpoint,
    CanonicalProvenance,
    CanonicalTransfer,
)


def _create_store(
    tmp_path: Path,
) -> ArchiveStore:
    """
    Create an ArchiveStore backed by a temporary SQLite database.
    """

    paths = ArchivePaths(
        root=tmp_path,
    )

    connection = sqlite3.connect(
        paths.database,
    )
    connection.row_factory = sqlite3.Row

    ArchiveSchema.create(
        connection,
    )

    return ArchiveStore(
        paths=paths,
        connection=connection,
    )


def test_provenance_round_trip_preserves_complete_history(
    tmp_path: Path,
) -> None:
    """
    A complete CanonicalProvenance history survives persistence
    and reconstruction through ArchiveStore.
    """

    started_at = datetime(
        2026,
        7,
        30,
        18,
        0,
        tzinfo=timezone.utc,
    )

    first_finished_at = datetime(
        2026,
        7,
        30,
        18,
        30,
        tzinfo=timezone.utc,
    )

    second_started_at = datetime(
        2026,
        7,
        31,
        9,
        0,
        tzinfo=timezone.utc,
    )

    source = CanonicalEndpoint(
        adapter="discord",
        identifier="discord-server-123",
        name="Original Discord Server",
    )

    fluxer = CanonicalEndpoint(
        adapter="fluxer",
        identifier="fluxer-server-456",
        name="Primary Fluxer Archive",
    )

    slack = CanonicalEndpoint(
        adapter="slack",
        identifier="slack-workspace-789",
        name="Slack Workspace",
    )

    first_transfer = CanonicalTransfer(
        source=source,
        destination=fluxer,
        started_at=started_at,
        finished_at=first_finished_at,
        imported_messages=1250,
        exported_messages=1250,
    )

    second_transfer = CanonicalTransfer(
        source=fluxer,
        destination=slack,
        started_at=second_started_at,
        finished_at=None,
        imported_messages=500,
        exported_messages=450,
    )

    provenance = CanonicalProvenance(
        history=(
            first_transfer,
            second_transfer,
        ),
    )

    store = _create_store(
        tmp_path,
    )

    try:
        for transfer in provenance.history:
            store.insert_provenance_transfer(
                transfer,
            )

        store.commit()

        reconstructed = CanonicalProvenance(
            history=tuple(
                store.iter_provenance_transfers()
            ),
        )

        assert reconstructed == provenance

    finally:
        store.close()


def test_provenance_endpoint_is_reused(
    tmp_path: Path,
) -> None:
    """
    Repeated use of the same adapter/identifier pair does not
    create duplicate endpoint records.
    """

    endpoint = CanonicalEndpoint(
        adapter="discord",
        identifier="server-123",
        name="Original Name",
    )

    updated_endpoint = CanonicalEndpoint(
        adapter="discord",
        identifier="server-123",
        name="Updated Name",
    )

    store = _create_store(
        tmp_path,
    )

    try:
        store.insert_provenance_endpoint(
            endpoint,
        )

        store.insert_provenance_endpoint(
            updated_endpoint,
        )

        endpoints = tuple(
            store.iter_provenance_endpoints()
        )

        assert endpoints == (
            updated_endpoint,
        )

    finally:
        store.close()


def test_provenance_supports_source_only_transfer(
    tmp_path: Path,
) -> None:
    """
    A transfer may have a source without a destination.

    This represents an archive ingestion operation whose eventual
    destination has not yet been recorded.
    """

    source = CanonicalEndpoint(
        adapter="discord",
        identifier="server-123",
        name="Discord Server",
    )

    transfer = CanonicalTransfer(
        source=source,
        destination=None,
        started_at=datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        ),
        imported_messages=100,
        exported_messages=0,
    )

    store = _create_store(
        tmp_path,
    )

    try:
        store.insert_provenance_transfer(
            transfer,
        )

        store.commit()

        transfers = tuple(
            store.iter_provenance_transfers()
        )

        assert transfers == (
            transfer,
        )

    finally:
        store.close()


def test_provenance_preserves_zero_message_transfer(
    tmp_path: Path,
) -> None:
    """
    A transfer with no messages is still a valid historical record.
    """

    source = CanonicalEndpoint(
        adapter="discord",
        identifier="server-123",
        name="Discord Server",
    )

    destination = CanonicalEndpoint(
        adapter="fluxer",
        identifier="server-456",
        name="Fluxer Server",
    )

    transfer = CanonicalTransfer(
        source=source,
        destination=destination,
        started_at=datetime(
            2026,
            7,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        ),
        finished_at=datetime(
            2026,
            7,
            30,
            12,
            1,
            tzinfo=timezone.utc,
        ),
        imported_messages=0,
        exported_messages=0,
    )

    store = _create_store(
        tmp_path,
    )

    try:
        store.insert_provenance_transfer(
            transfer,
        )

        store.commit()

        transfers = tuple(
            store.iter_provenance_transfers()
        )

        assert transfers == (
            transfer,
        )

    finally:
        store.close()
