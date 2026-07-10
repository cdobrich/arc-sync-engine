"""
Identity synchronization operations.
"""

from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.models import CanonicalIdentity

from .base import SyncOperation


@dataclass(frozen=True, slots=True)
class CreateIdentityOperation(SyncOperation):

    identity: CanonicalIdentity


@dataclass(frozen=True, slots=True)
class UpdateIdentityOperation(SyncOperation):

    identity: CanonicalIdentity