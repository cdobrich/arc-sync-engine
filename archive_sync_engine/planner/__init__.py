"""
Synchronization planner.

The Planner compares the canonical Archive with the destination state
and produces a dependency-safe stream of SyncOperations.
"""

from .planner import Planner

__all__ = [
    "Planner",
]