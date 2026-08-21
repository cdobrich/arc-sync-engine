"""
StateRepository interfaces.

StateRepositories persist operational state used by the Archive Sync Engine.

Unlike the Archive, repositories do not own canonical content.

Instead they store engine metadata such as:

- import sessions
- sync sessions
- destination mappings
- importer state
- future planner metadata
"""
from .execution_log import ExecutionLogEntry, SQLiteExecutionLog
from .in_memory_state_repository import InMemoryStateRepository
from .sqlite_state_repository import SQLiteStateRepository
from .state_repository import StateRepository
from .scope import synchronization_state_path, synchronization_state_paths

__all__ = [
    "ExecutionLogEntry",
    "InMemoryStateRepository",
    "SQLiteExecutionLog",
    "StateRepository",
    "synchronization_state_path",
    "synchronization_state_paths",
]
