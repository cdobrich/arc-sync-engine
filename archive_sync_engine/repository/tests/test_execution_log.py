from __future__ import annotations

import sqlite3

import pytest

from archive_sync_engine.repository.execution_log import SQLiteExecutionLog


def _database(path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE execution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_type TEXT NOT NULL,
            canonical_id TEXT,
            deleted INTEGER NOT NULL,
            deleted_entity TEXT
        )
        """,
    )
    connection.executemany(
        """
        INSERT INTO execution_log (
            operation_type,
            canonical_id,
            deleted,
            deleted_entity
        ) VALUES (?, ?, ?, ?)
        """,
        (
            ("CreateMessageOperation", "message-1", 0, None),
            ("DeleteMessageOperation", "message-2", 1, "message"),
            ("EditMessageOperation", "message-1", 0, None),
        ),
    )
    connection.commit()
    connection.close()


def test_execution_log_returns_newest_successful_operations_first(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    _database(path)

    with SQLiteExecutionLog(path) as log:
        entries = log.query(limit=2)

    assert [entry.operation_type for entry in entries] == [
        "EditMessageOperation",
        "DeleteMessageOperation",
    ]
    assert entries[1].deleted is True
    assert entries[1].deleted_entity == "message"


def test_execution_log_filters_by_canonical_id_and_operation(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    _database(path)

    with SQLiteExecutionLog(path) as log:
        entries = log.query(
            canonical_id="message-1",
            operation_type="EditMessageOperation",
        )

    assert entries == (
        entries[0],
    )
    assert entries[0].canonical_id == "message-1"
    assert entries[0].operation_type == "EditMessageOperation"


def test_execution_log_count_supports_deletion_filter(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    _database(path)

    with SQLiteExecutionLog(path) as log:
        assert log.count(deleted=True) == 1
        assert log.count(deleted=False) == 2


def test_execution_log_rejects_non_positive_limit(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    _database(path)

    with SQLiteExecutionLog(path) as log:
        with pytest.raises(ValueError, match="limit must be positive"):
            log.query(limit=0)
