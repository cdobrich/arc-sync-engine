"""
Synchronization state.

A SynchronizationState is an immutable snapshot of the synchronization
metadata required by the Planner to compute synchronization work.

The state records:

    * destination references; and
    * the canonical fingerprint last successfully synchronized.

The Planner can therefore determine whether an entity is new, changed,
unchanged, or stale.
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

    Destination references identify corresponding destination objects.

    Fingerprints identify the canonical state that was successfully
    synchronized for each corresponding object.
    """

    conversations: dict[
        str,
        DestinationConversationRef,
    ] = field(
        default_factory=dict,
    )

    identities: dict[
        str,
        DestinationIdentityRef,
    ] = field(
        default_factory=dict,
    )

    messages: dict[
        str,
        DestinationMessageRef,
    ] = field(
        default_factory=dict,
    )

    conversation_fingerprints: dict[
        str,
        str,
    ] = field(
        default_factory=dict,
    )

    identity_fingerprints: dict[
        str,
        str,
    ] = field(
        default_factory=dict,
    )

    message_fingerprints: dict[
        str,
        str,
    ] = field(
        default_factory=dict,
    )

    def with_conversation(
        self,
        canonical_id: str,
        destination_ref: DestinationConversationRef,
        fingerprint: str | None = None,
    ) -> SynchronizationState:
        """
        Return a new state containing a destination conversation
        reference and optional canonical fingerprint.
        """

        conversations = dict(
            self.conversations,
        )

        conversations[canonical_id] = destination_ref

        fingerprints = dict(
            self.conversation_fingerprints,
        )

        if fingerprint is not None:
            fingerprints[canonical_id] = fingerprint

        return SynchronizationState(
            conversations=conversations,
            identities=dict(
                self.identities,
            ),
            messages=dict(
                self.messages,
            ),
            conversation_fingerprints=fingerprints,
            identity_fingerprints=dict(
                self.identity_fingerprints,
            ),
            message_fingerprints=dict(
                self.message_fingerprints,
            ),
        )

    def with_identity(
        self,
        identity_key: str,
        destination_ref: DestinationIdentityRef,
        fingerprint: str | None = None,
    ) -> SynchronizationState:
        """
        Return a new state containing a destination identity
        reference and optional canonical fingerprint.
        """

        identities = dict(
            self.identities,
        )

        identities[identity_key] = destination_ref

        fingerprints = dict(
            self.identity_fingerprints,
        )

        if fingerprint is not None:
            fingerprints[identity_key] = fingerprint

        return SynchronizationState(
            conversations=dict(
                self.conversations,
            ),
            identities=identities,
            messages=dict(
                self.messages,
            ),
            conversation_fingerprints=dict(
                self.conversation_fingerprints,
            ),
            identity_fingerprints=fingerprints,
            message_fingerprints=dict(
                self.message_fingerprints,
            ),
        )

    def with_message(
        self,
        canonical_id: str,
        destination_ref: DestinationMessageRef,
        fingerprint: str | None = None,
    ) -> SynchronizationState:
        """
        Return a new state containing a destination message
        reference and optional canonical fingerprint.
        """

        messages = dict(
            self.messages,
        )

        messages[canonical_id] = destination_ref

        fingerprints = dict(
            self.message_fingerprints,
        )

        if fingerprint is not None:
            fingerprints[canonical_id] = fingerprint

        return SynchronizationState(
            conversations=dict(
                self.conversations,
            ),
            identities=dict(
                self.identities,
            ),
            messages=messages,
            conversation_fingerprints=dict(
                self.conversation_fingerprints,
            ),
            identity_fingerprints=dict(
                self.identity_fingerprints,
            ),
            message_fingerprints=fingerprints,
        )

    def without_conversation(
        self,
        canonical_id: str,
    ) -> SynchronizationState:
        """
        Return a new state without a synchronized conversation.
        """

        conversations = dict(
            self.conversations,
        )

        conversations.pop(
            canonical_id,
            None,
        )

        fingerprints = dict(
            self.conversation_fingerprints,
        )

        fingerprints.pop(
            canonical_id,
            None,
        )

        return SynchronizationState(
            conversations=conversations,
            identities=dict(
                self.identities,
            ),
            messages=dict(
                self.messages,
            ),
            conversation_fingerprints=fingerprints,
            identity_fingerprints=dict(
                self.identity_fingerprints,
            ),
            message_fingerprints=dict(
                self.message_fingerprints,
            ),
        )

    def without_message(
        self,
        canonical_id: str,
    ) -> SynchronizationState:
        """
        Return a new state without a synchronized message.
        """

        messages = dict(
            self.messages,
        )

        messages.pop(
            canonical_id,
            None,
        )

        fingerprints = dict(
            self.message_fingerprints,
        )

        fingerprints.pop(
            canonical_id,
            None,
        )

        return SynchronizationState(
            conversations=dict(
                self.conversations,
            ),
            identities=dict(
                self.identities,
            ),
            messages=messages,
            conversation_fingerprints=dict(
                self.conversation_fingerprints,
            ),
            identity_fingerprints=dict(
                self.identity_fingerprints,
            ),
            message_fingerprints=fingerprints,
        )

    def without_identity(
        self,
        canonical_id: str,
    ) -> SynchronizationState:
        """
        Return a new state without a synchronized identity.
        """

        identities = dict(
            self.identities,
        )

        identities.pop(
            canonical_id,
            None,
        )

        fingerprints = dict(
            self.identity_fingerprints,
        )

        fingerprints.pop(
            canonical_id,
            None,
        )

        return SynchronizationState(
            conversations=dict(
                self.conversations,
            ),
            identities=identities,
            messages=dict(
                self.messages,
            ),
            conversation_fingerprints=dict(
                self.conversation_fingerprints,
            ),
            identity_fingerprints=fingerprints,
            message_fingerprints=dict(
                self.message_fingerprints,
            ),
        )

    def apply_execution_result(
        self,
        canonical_id: str | None,
        result: ExecutionResult,
    ) -> SynchronizationState:
        """
        Return a new state containing the result of execution.

        Results that contain no destination reference do not alter
        synchronization state unless the result represents a deletion.

        A result containing multiple destination references is rejected.

        Deleted entities are removed from synchronization state.
        """

        if canonical_id is None:
            return self

        if result.deleted:

            references = (
                result.conversation is not None,
                result.identity is not None,
                result.message is not None,
            )

            if any(
                references,
            ):
                raise ValueError(
                    "Deleted ExecutionResult cannot contain "
                    "destination references."
                )

            raise RuntimeError(
                "Deleted ExecutionResult requires operation-specific "
                "state removal."
            )

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
                result.canonical_fingerprint,
            )

        if result.identity is not None:
            return self.with_identity(
                canonical_id,
                result.identity,
                result.canonical_fingerprint,
            )

        if result.message is not None:
            return self.with_message(
                canonical_id,
                result.message,
                result.canonical_fingerprint,
            )

        return self