"""
Execution-log records exposed by StateRepository implementations.
"""

from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.executor.result import DeletedEntityType


@dataclass(frozen=True, slots=True)
class ExecutionLogEntry:
    """
    Durable record of one successfully checkpointed synchronization operation.

    The log describes execution metadata only. It is not a second
    synchronization-state source of truth and does not contain canonical
    entity data.
    """

    id: int
    operation_type: str
    canonical_id: str | None
    deleted: bool
    deleted_entity: DeletedEntityType | None
