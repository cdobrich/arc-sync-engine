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
from .in_memory_state_repository import InMemoryStateRepository
from .sqlite_state_repository import SQLiteStateRepository
from .state_repository import StateRepository

__all__ = [
    "InMemoryStateRepository",
    "SQLiteStateRepository",
    "StateRepository",
]
