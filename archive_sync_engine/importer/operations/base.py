"""
Base classes for import operations.

ImportOperations describe atomic units of work performed while acquiring
canonical information from a SourceAdapter.

Examples include:

- importing a conversation
- importing an identity
- importing a message
- downloading an attachment
- storing an attachment

ImportOperations intentionally belong only to the acquisition pipeline.

They are not synchronization operations and are never produced by the
Planner.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImportOperation(ABC):
    """
    Base class for every atomic import operation.

    Import operations are immutable value objects describing a single
    unit of acquisition work.
    """