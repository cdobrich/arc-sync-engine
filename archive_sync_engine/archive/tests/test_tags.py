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


def test_tag_rename_preserves_immutable_identity_and_sequence(tmp_path: Path) -> None:
    registry = ArchiveTagRegistry(tmp_path / "tags.json")
    created = datetime(2026, 10, 13, tzinfo=UTC)
    tag = registry.create("Discord Export v1", created_at=created)
    other = registry.create("Discord Export v2", created_at=created)

    renamed = registry.rename(tag.id, "Discord Export v1 — renamed")

    assert renamed.id == tag.id
    assert renamed.sequence == tag.sequence
    assert renamed.created_at == tag.created_at
    assert renamed.name == "Discord Export v1 — renamed"
    assert registry.get(tag.id) == renamed
    assert registry.get("Discord Export v1") is None
    assert registry.get(other.name) == other


def test_tag_delete_is_a_persistent_tombstone(tmp_path: Path) -> None:
    registry = ArchiveTagRegistry(tmp_path / "tags.json")
    created = datetime(2026, 10, 13, tzinfo=UTC)
    deleted_at = datetime(2026, 10, 14, tzinfo=UTC)
    tag = registry.create("Discord Export v1", created_at=created)

    deleted = registry.delete(tag.id, deleted_at=deleted_at)

    assert deleted.id == tag.id
    assert deleted.sequence == tag.sequence
    assert deleted.name == tag.name
    assert deleted.deleted_at == deleted_at
    assert registry.get(tag.id) == deleted
    assert registry.get(tag.name) is None
    assert tuple(registry.iter_tags()) == (deleted,)

    reloaded = ArchiveTagRegistry(tmp_path / "tags.json")
    assert reloaded.require(tag.id).deleted_at == deleted_at


def test_deleted_tag_remains_a_range_boundary_by_immutable_id(tmp_path: Path) -> None:
    registry = ArchiveTagRegistry(tmp_path / "tags.json")
    created = datetime(2026, 10, 13, tzinfo=UTC)
    first = registry.create("v1", created_at=created)
    deleted = registry.create("v2", created_at=created)
    third = registry.create("v3", created_at=created)
    registry.delete(deleted.id, deleted_at=datetime(2026, 10, 14, tzinfo=UTC))

    assert tuple(tag.id for tag in registry.between(first.id, third.id)) == (deleted.id,)
    assert tuple(tag.id for tag in registry.between(first.id, third.id, inclusive=True)) == (first.id, deleted.id, third.id)


def test_deleted_tag_name_may_be_reused_but_identity_is_distinct(tmp_path: Path) -> None:
    registry = ArchiveTagRegistry(tmp_path / "tags.json")
    created = datetime(2026, 10, 13, tzinfo=UTC)
    original = registry.create("release", created_at=created)
    registry.delete(original.id, deleted_at=datetime(2026, 10, 14, tzinfo=UTC))

    replacement = registry.create("release", created_at=datetime(2026, 10, 15, tzinfo=UTC))

    assert replacement.id != original.id
    assert replacement.sequence > original.sequence
    assert registry.get("release") == replacement
    assert registry.get(original.id).deleted_at is not None


def test_tag_rename_rejects_duplicate_name_and_deleted_tag(tmp_path: Path) -> None:
    registry = ArchiveTagRegistry(tmp_path / "tags.json")
    created = datetime(2026, 10, 13, tzinfo=UTC)
    first = registry.create("v1", created_at=created)
    second = registry.create("v2", created_at=created)

    with pytest.raises(ValueError, match="already exists"):
        registry.rename(second.id, "v1")

    registry.delete(first.id, deleted_at=datetime(2026, 10, 14, tzinfo=UTC))
    with pytest.raises(ValueError, match="cannot rename"):
        registry.rename(first.id, "restored")


def test_tag_fingerprint_detects_database_state_change(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    package = ArchivePackage.initialize(ArchivePaths(archive_path))
    tag = package.create_tag("v1", created_at=datetime(2026, 10, 13, tzinfo=UTC))

    assert package.tag_matches_current_database(tag.id)

    database = ArchivePaths(archive_path).database
    database.write_bytes(database.read_bytes() + b"x")

    assert not package.tag_matches_current_database(tag.id)
