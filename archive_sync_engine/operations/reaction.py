"""
Reaction synchronization operations.
"""

from __future__ import annotations

from dataclasses import dataclass

from archive_sync_engine.models import CanonicalReaction

from .base import SyncOperation


@dataclass(frozen=True, slots=True)
class AddReactionOperation(SyncOperation):

    reaction: CanonicalReaction


@dataclass(frozen=True, slots=True)
class RemoveReactionOperation(SyncOperation):

    reaction: CanonicalReaction