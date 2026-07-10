"""
Message import operations.
"""

from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.models import CanonicalMessage

from .base import ImportOperation


@dataclass(frozen=True, slots=True)
class ImportMessageOperation(ImportOperation):
    """
    Import a canonical message into the Archive.
    """

    message: CanonicalMessage