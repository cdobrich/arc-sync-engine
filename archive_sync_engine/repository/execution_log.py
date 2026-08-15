"""Read-only synchronization execution diagnostics.

The SQLite repository already records one execution row for each successful
synchronization operation. This module exposes that history for diagnostics
without making diagnostics responsible for synchronization decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3


@dataclass(frozen=True, slots=True)
class ExecutionLogEntry:
    """One successful synchronization execution record."""

    id: int
    operation_type: str
    canonical_id: str | None
    deleted: bool
    deleted_entity: str | None


class SQLiteExecutionLog:
    """Read-only query surface over a StateRepository SQLite database.

    This class deliberately opens its own read-only connection. It cannot
    mutate synchronization state and never participates in planning or
    execution.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._connection = sqlite3.connect(
            f"file:{Path(self._path).resolve()}?mode=ro",
            uri=True,
        )
        self._connection.row_factory = sqlite3.Row

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SQLiteExecutionLog":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def query(
        self,
        *,
        limit: int = 100,
        canonical_id: str | None = None,
        operation_type: str | None = None,
        deleted: bool | None = None,
    ) -> tuple[ExecutionLogEntry, ...]:
        """Return matching successful execution records, newest first."""

        if limit <= 0:
            raise ValueError("Execution-log query limit must be positive.")

        clauses: list[str] = []
        parameters: list[object] = []

        if canonical_id is not None:
            clauses.append("canonical_id = ?")
            parameters.append(canonical_id)

        if operation_type is not None:
            clauses.append("operation_type = ?")
            parameters.append(operation_type)

        if deleted is not None:
            clauses.append("deleted = ?")
            parameters.append(int(deleted))

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        rows = self._connection.execute(
            f"""
            SELECT id, operation_type, canonical_id, deleted, deleted_entity
            FROM execution_log
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            (*parameters, limit),
        ).fetchall()

        return tuple(
            ExecutionLogEntry(
                id=int(row["id"]),
                operation_type=str(row["operation_type"]),
                canonical_id=(
                    str(row["canonical_id"])
                    if row["canonical_id"] is not None
                    else None
                ),
                deleted=bool(row["deleted"]),
                deleted_entity=(
                    str(row["deleted_entity"])
                    if row["deleted_entity"] is not None
                    else None
                ),
            )
            for row in rows
        )

    def count(
        self,
        *,
        canonical_id: str | None = None,
        operation_type: str | None = None,
        deleted: bool | None = None,
    ) -> int:
        """Return the number of matching successful executions."""

        clauses: list[str] = []
        parameters: list[object] = []

        if canonical_id is not None:
            clauses.append("canonical_id = ?")
            parameters.append(canonical_id)
        if operation_type is not None:
            clauses.append("operation_type = ?")
            parameters.append(operation_type)
        if deleted is not None:
            clauses.append("deleted = ?")
            parameters.append(int(deleted))

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        row = self._connection.execute(
            f"SELECT COUNT(*) FROM execution_log {where}",
            parameters,
        ).fetchone()
        return int(row[0])
