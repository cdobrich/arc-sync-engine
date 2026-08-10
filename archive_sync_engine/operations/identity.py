"""
Identity synchronization operations.
"""

from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.models import CanonicalIdentity
from archive_sync_engine.models.ids import IdentityKey

from .base import SyncOperation


@dataclass(frozen=True, slots=True)
class CreateIdentityOperation(SyncOperation):

    identity: CanonicalIdentity


@dataclass(frozen=True, slots=True)
class UpdateIdentityOperation(SyncOperation):

    identity: CanonicalIdentity

@dataclass(frozen=True, slots=True)
class DeleteIdentityOperation(SyncOperation):
    """Delete a synchronized identity that no longer exists in the Archive."""

    identity_key: IdentityKey
