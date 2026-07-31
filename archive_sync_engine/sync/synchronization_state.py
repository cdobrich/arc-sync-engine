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
from archive_sync_engine.executor.result import ExecutionResult


@dataclass(frozen=True, slots=True)
class SynchronizationState:
    """
    Immutable synchronization snapshot.

    The dictionaries map canonical identifiers to destination
    references that already exist on the destination platform.

    The state is deliberately immutable. A coordinator or repository
    creates a new snapshot when execution produces new synchronization
    metadata.
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

    def with_conversation(
        self,
        canonical_id: str,
        destination_ref: DestinationConversationRef,
    ) -> SynchronizationState:
        """
        Return a new state containing a destination conversation reference.
        """

        conversations = dict(
            self.conversations,
        )

        conversations[canonical_id] = destination_ref

        return SynchronizationState(
            conversations=conversations,
            identities=dict(
                self.identities,
            ),
            messages=dict(
                self.messages,
            ),
        )

    def with_identity(
        self,
        identity_key: str,
        destination_ref: DestinationIdentityRef,
    ) -> SynchronizationState:
        """
        Return a new state containing a destination identity reference.
        """

        identities = dict(
            self.identities,
        )

        identities[identity_key] = destination_ref

        return SynchronizationState(
            conversations=dict(
                self.conversations,
            ),
            identities=identities,
            messages=dict(
                self.messages,
            ),
        )

    def with_message(
        self,
        canonical_id: str,
        destination_ref: DestinationMessageRef,
    ) -> SynchronizationState:
        """
        Return a new state containing a destination message reference.
        """

        messages = dict(
            self.messages,
        )

        messages[canonical_id] = destination_ref

        return SynchronizationState(
            conversations=dict(
                self.conversations,
            ),
            identities=dict(
                self.identities,
            ),
            messages=messages,
        )

    def apply_execution_result(
        self,
        canonical_id: str,
        result: ExecutionResult,
    ) -> SynchronizationState:
        """
        Return a new state containing references produced by an execution.

        The result determines which synchronization-state collection is
        updated.

        An execution result that contains no destination reference does
        not change synchronization state.

        A result containing more than one reference is rejected because
        one SyncOperation represents one atomic synchronization action.
        """

        references = (
            result.conversation is not None,
            result.identity is not None,
            result.message is not None,
        )

        reference_count = sum(
            references,
        )

        if reference_count > 1:
            raise ValueError(
                "ExecutionResult cannot contain multiple destination "
                "references."
            )

        if result.conversation is not None:
            return self.with_conversation(
                canonical_id,
                result.conversation,
            )

        if result.identity is not None:
            return self.with_identity(
                canonical_id,
                result.identity,
            )

        if result.message is not None:
            return self.with_message(
                canonical_id,
                result.message,
            )

        return self