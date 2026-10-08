from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from archive_sync_engine.archive.package import ArchivePackage
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.tags import (
    ArchiveTagRegistry,
    ArchiveTagSourceState,
    ArchiveTagSourceStatus,
)
from archive_sync_engine.sync.run_configuration import (
    RunDirection,
    SyncRunConfiguration,
)
from archive_sync_engine.sync.session import SyncDirection, SyncSession


UTC = timezone.utc


def test_tag_round_trip_and_ordered_range(tmp_path: Path) -> None:
    registry = ArchiveTagRegistry(tmp_path / "tags.json")
    first_time = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    second_time = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    third_time = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)

    first = registry.create("Discord Export v1, 2026-10-13", created_at=first_time)
    second = registry.create("Discord Export v2, 2026-10-20", created_at=second_time)
    third = registry.create("Discord Export v3, 2026-10-27", created_at=third_time)

    assert first.sequence == 1
    assert second.sequence == 2
    assert third.sequence == 3
    assert registry.get(first.name) == first
    assert registry.get(second.id) == second
    assert tuple(registry.iter_tags()) == (first, second, third)
    assert registry.between(first.name, third.name) == (second,)
    assert registry.between(first.name, third.name, inclusive=True) == (first, second, third)


def test_tag_names_are_unique_and_boundaries_are_ordered(tmp_path: Path) -> None:
    registry = ArchiveTagRegistry(tmp_path / "tags.json")
    now = datetime(2026, 10, 13, tzinfo=UTC)
    registry.create("v1", created_at=now)
    registry.create("v2", created_at=now)

    with pytest.raises(ValueError, match="already exists"):
        registry.create("v1", created_at=now)

    with pytest.raises(ValueError, match="start tag must not follow"):
        registry.between("v2", "v1")

    with pytest.raises(KeyError, match="Archive tag not found"):
        registry.require("missing")


def test_package_tag_captures_completed_source_import_state(tmp_path: Path) -> None:
    paths = ArchivePaths(tmp_path)
    package = ArchivePackage(paths)
    started = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
    finished = datetime(2026, 10, 13, 12, 30, tzinfo=UTC)

    package.save_run_configuration(
        SyncRunConfiguration(
            direction=RunDirection.IMPORT,
            input_adapter="Discord",
            input_scope=("server-123",),
        )
    )
    package.save_session(
        SyncSession(
            id="import-123",
            direction=SyncDirection.IMPORT,
            started_at=started,
            updated_at=finished,
            completed=True,
            checkpoint="conversation-999",
        )
    )

    tag = package.create_tag("Discord Export v1, 2026-10-13", created_at=finished)

    assert tag.source is not None
    assert tag.source.adapter == "discord"
    assert tag.source.scope == ("server-123",)
    assert tag.source.session_id == "import-123"
    assert tag.source.status is ArchiveTagSourceStatus.COMPLETED
    assert tag.source.started_at == started
    assert tag.source.updated_at == finished
    assert tag.source.checkpoint == "conversation-999"
    assert package.get_tag(tag.id) == tag


def test_package_tag_captures_failed_source_import_state(tmp_path: Path) -> None:
    paths = ArchivePaths(tmp_path)
    package = ArchivePackage(paths)
    started = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    failed = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)

    package.save_run_configuration(
        SyncRunConfiguration(
            direction=RunDirection.IMPORT,
            input_adapter="fluxer",
            input_scope=("workspace-456",),
        )
    )
    session = SyncSession(
        id="import-456",
        direction=SyncDirection.IMPORT,
        started_at=started,
        updated_at=failed,
        checkpoint="conversation-17",
    )
    session.fail("upstream unavailable")
    package.save_session(session)

    tag = package.create_tag("Interrupted Fluxer import", created_at=failed)

    assert tag.source is not None
    assert tag.source.status is ArchiveTagSourceStatus.FAILED
    assert tag.source.error == "upstream unavailable"
    assert tag.source.updated_at == session.updated_at


def test_non_import_session_does_not_claim_source_import(tmp_path: Path) -> None:
    paths = ArchivePaths(tmp_path)
    package = ArchivePackage(paths)
    now = datetime(2026, 10, 13, tzinfo=UTC)

    package.save_run_configuration(
        SyncRunConfiguration(
            direction=RunDirection.SYNC,
            input_adapter="discord",
            input_scope=("server-123",),
            destination_adapter="fluxer",
            destination_scope=("workspace-456",),
        )
    )
    package.save_session(
        SyncSession(
            id="export-1",
            direction=SyncDirection.EXPORT,
            started_at=now,
            updated_at=now,
            completed=True,
        )
    )

    tag = package.create_tag("After export", created_at=now)

    assert tag.source is None


def test_tag_uses_durable_last_import_after_session_is_replaced(tmp_path: Path) -> None:
    paths = ArchivePaths(tmp_path)
    package = ArchivePackage(paths)
    imported_at = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)

    source = ArchiveTagSourceState(
        adapter="discord",
        scope=("server-123",),
        session_id="import-123",
        status=ArchiveTagSourceStatus.COMPLETED,
        started_at=datetime(2026, 10, 7, 9, 0, tzinfo=UTC),
        updated_at=imported_at,
        checkpoint="conversation-999",
        error=None,
    )
    package.save_last_import_source_state(source)

    # A later export/sync replaces the active session; the historical source
    # import state must remain available to a future manual tag.
    package.save_session(
        SyncSession(
            id="export-999",
            direction=SyncDirection.EXPORT,
            started_at=imported_at,
            updated_at=imported_at,
            completed=True,
        )
    )

    tag = package.create_tag("Post-export checkpoint", created_at=imported_at)

    assert tag.source == source
