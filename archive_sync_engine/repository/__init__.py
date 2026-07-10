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

from .state_repository import StateRepository

__all__ = [
    "StateRepository",
]
