"""
Synchronization state.

A SynchronizationState is an immutable snapshot of the synchronization
metadata required by the Planner to compute synchronization work.

Unlike ImportState, this is not opaque implementation state.

Instead, it represents engine-owned synchronization metadata that has
been loaded from the StateRepository.

The Planner must treat this object as read-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)


@dataclass(frozen=True, slots=True)
class SynchronizationState:
    """
    Immutable synchronization snapshot.

    The dictionaries map canonical identifiers to destination
    references that already exist on the destination platform.
    """

    conversations: dict[str, DestinationConversationRef] = field(
        default_factory=dict,
    )

    identities: dict[str, DestinationIdentityRef] = field(
        default_factory=dict,
    )

    messages: dict[str, DestinationMessageRef] = field(
        default_factory=dict,
    )