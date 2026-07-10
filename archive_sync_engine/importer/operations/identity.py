"""
Identity import operations.
"""

from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.models import CanonicalIdentity

from .base import ImportOperation


@dataclass(frozen=True, slots=True)
class ImportIdentityOperation(ImportOperation):
    """
    Import a canonical identity into the Archive.
    """

    identity: CanonicalIdentity