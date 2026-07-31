from __future__ import annotations

from datetime import datetime, timezone

import pytest

from archive_sync_engine.sync.session import (
    SyncDirection,
    SyncSession,
)


def test_import_session_json_round_trip() -> None:
    session = SyncSession(
        id="session-import-001",
        direction=SyncDirection.IMPORT,
        started_at=datetime(
            2026,
            7,
            30,
            18,
            0,
            tzinfo=timezone.utc,
        ),
        updated_at=datetime(
            2026,
            7,
            30,
            18,
            15,
            tzinfo=timezone.utc,
        ),
        paused=True,
        checkpoint="source-cursor-123",
    )

    restored = SyncSession.from_json_dict(
        session.to_json_dict(),
    )

    assert restored == session


def test_export_session_json_round_trip() -> None:
    session = SyncSession(
        id="session-export-001",
        direction=SyncDirection.EXPORT,
        started_at=datetime(
            2026,
            7,
            30,
            19,
            0,
            tzinfo=timezone.utc,
        ),
        updated_at=datetime(
            2026,
            7,
            30,
            19,
            30,
            tzinfo=timezone.utc,
        ),
        completed=True,
        checkpoint="message-987",
    )

    restored = SyncSession.from_json_dict(
        session.to_json_dict(),
    )

    assert restored == session


def test_session_preserves_error_state() -> None:
    session = SyncSession(
        id="session-export-error-001",
        direction=SyncDirection.EXPORT,
        started_at=datetime(
            2026,
            7,
            30,
            20,
            0,
            tzinfo=timezone.utc,
        ),
        updated_at=datetime(
            2026,
            7,
            30,
            20,
            5,
            tzinfo=timezone.utc,
        ),
        error="Destination endpoint unavailable.",
        checkpoint="message-123",
    )

    restored = SyncSession.from_json_dict(
        session.to_json_dict(),
    )

    assert restored == session

def test_session_can_pause_and_resume() -> None:
    session = SyncSession(
        id="session-import-pause-001",
        direction=SyncDirection.IMPORT,
        started_at=datetime(
            2026,
            7,
            30,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        updated_at=datetime(
            2026,
            7,
            30,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        checkpoint="source-cursor-100",
    )

    session.pause()

    assert session.paused is True
    assert session.checkpoint == "source-cursor-100"

    session.resume()

    assert session.paused is False
    assert session.checkpoint == "source-cursor-100"


def test_session_can_advance_checkpoint() -> None:
    session = SyncSession(
        id="session-import-checkpoint-001",
        direction=SyncDirection.IMPORT,
        started_at=datetime(
            2026,
            7,
            30,
            21,
            15,
            tzinfo=timezone.utc,
        ),
        updated_at=datetime(
            2026,
            7,
            30,
            21,
            15,
            tzinfo=timezone.utc,
        ),
    )

    session.advance_checkpoint(
        "source-cursor-200",
    )

    assert session.checkpoint == "source-cursor-200"
    assert session.error is None


def test_session_failure_preserves_checkpoint() -> None:
    session = SyncSession(
        id="session-export-failure-001",
        direction=SyncDirection.EXPORT,
        started_at=datetime(
            2026,
            7,
            30,
            21,
            30,
            tzinfo=timezone.utc,
        ),
        updated_at=datetime(
            2026,
            7,
            30,
            21,
            30,
            tzinfo=timezone.utc,
        ),
        checkpoint="message-100",
    )

    session.fail(
        "Destination endpoint unavailable.",
    )

    assert session.error == "Destination endpoint unavailable."
    assert session.checkpoint == "message-100"
    assert session.completed is False
    assert session.cancelled is False


def test_completed_session_cannot_advance_checkpoint() -> None:
    session = SyncSession(
        id="session-complete-001",
        direction=SyncDirection.EXPORT,
        started_at=datetime(
            2026,
            7,
            30,
            22,
            0,
            tzinfo=timezone.utc,
        ),
        updated_at=datetime(
            2026,
            7,
            30,
            22,
            0,
            tzinfo=timezone.utc,
        ),
    )

    session.complete()

    with pytest.raises(RuntimeError):
        session.advance_checkpoint(
            "message-200",
        )


def test_cancelled_session_cannot_resume() -> None:
    session = SyncSession(
        id="session-cancelled-001",
        direction=SyncDirection.IMPORT,
        started_at=datetime(
            2026,
            7,
            30,
            22,
            15,
            tzinfo=timezone.utc,
        ),
        updated_at=datetime(
            2026,
            7,
            30,
            22,
            15,
            tzinfo=timezone.utc,
        ),
    )

    session.cancel()

    with pytest.raises(RuntimeError):
        session.resume()


def test_unpaused_session_cannot_resume() -> None:
    session = SyncSession(
        id="session-not-paused-001",
        direction=SyncDirection.EXPORT,
        started_at=datetime(
            2026,
            7,
            30,
            22,
            30,
            tzinfo=timezone.utc,
        ),
        updated_at=datetime(
            2026,
            7,
            30,
            22,
            30,
            tzinfo=timezone.utc,
        ),
    )

    with pytest.raises(RuntimeError):
        session.resume()
