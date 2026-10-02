from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.store import ArchiveStore
from archive_sync_engine.archive.writer import ArchiveWriter
from archive_sync_engine.models.provenance import (
    CanonicalEndpoint,
    CanonicalTransfer,
)


def test_writer_records_incremental_transfer(
    tmp_path: Path,
) -> None:
    """
    ArchiveWriter can append one provenance transfer without
    replacing existing history.
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

    first_transfer = CanonicalTransfer(
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
    )

    second_transfer = CanonicalTransfer(
        source=destination,
        destination=source,
        started_at=datetime(
            2026,
            7,
            31,
            9,
            0,
            tzinfo=timezone.utc,
        ),
        finished_at=datetime(
            2026,
            7,
            31,
            9,
            15,
            tzinfo=timezone.utc,
        ),
        imported_messages=25,
        exported_messages=25,
    )

    writer = ArchiveWriter(
        paths,
    )

    try:
        writer.record_transfer(
            first_transfer,
        )

        writer.commit()

        writer.record_transfer(
            second_transfer,
        )

        writer.commit()

    finally:
        writer.close()

    store = ArchiveStore.open(
        paths,
    )

    try:
        transfers = tuple(
            store.iter_provenance_transfers(),
        )

        assert transfers == (
            first_transfer,
            second_transfer,
        )

    finally:
        store.close()

def test_writer_existing_conversation_ids_returns_only_existing_ids(
    tmp_path: Path,
) -> None:
    """Bulk conversation lookup returns only IDs already persisted in the Archive."""
    from archive_sync_engine.models import CanonicalConversation, ConversationType
    from archive_sync_engine.models.ids import ConversationId

    paths = ArchivePaths(root=tmp_path)
    existing = CanonicalConversation(
        id=ConversationId("conversation-existing"),
        conversation_type=ConversationType.CHANNEL,
        title="existing",
    )

    with ArchiveWriter(paths) as writer:
        writer.add_conversation(existing)
        writer.commit()

        assert writer.existing_conversation_ids(
            (
                existing.id,
                ConversationId("conversation-missing"),
                existing.id,
            )
        ) == {"conversation-existing"}
        assert writer.existing_conversation_ids(()) == set()

