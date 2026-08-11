"""
In-memory execution context.

ExecutionContext retains destination references produced while executing
a synchronization operation sequence.

The context belongs to one execution and is never persisted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)
from archive_sync_engine.executor.errors import (
    MissingDestinationReferenceError,
)
from archive_sync_engine.models.ids import (
    ConversationId,
    IdentityKey,
    MessageId,
)

if TYPE_CHECKING:
    from archive_sync_engine.sync.synchronization_state import SynchronizationState


@dataclass(slots=True)
class ExecutionContext:
    """
    Destination references produced during one execution.

    Canonical identifiers remain the keys. Destination references remain
    opaque values supplied by the DestinationAdapter.
    """

    conversations: dict[
        ConversationId,
        DestinationConversationRef,
    ] = field(
        default_factory=dict,
    )

    identities: dict[
        IdentityKey,
        DestinationIdentityRef,
    ] = field(
        default_factory=dict,
    )

    messages: dict[
        MessageId,
        DestinationMessageRef,
    ] = field(
        default_factory=dict,
    )

    @classmethod
    def from_synchronization_state(
        cls,
        state: "SynchronizationState",
    ) -> "ExecutionContext":
        """Create an execution context seeded from persisted references."""

        context = cls()
        context.conversations.update({
            ConversationId(canonical_id): destination_ref
            for canonical_id, destination_ref in state.conversations.items()
        })
        context.identities.update({
            IdentityKey(canonical_id): destination_ref
            for canonical_id, destination_ref in state.identities.items()
        })
        context.messages.update({
            MessageId(canonical_id): destination_ref
            for canonical_id, destination_ref in state.messages.items()
        })
        return context

    def record_conversation(
        self,
        canonical_id: ConversationId,
        destination_ref: DestinationConversationRef,
    ) -> None:
        """
        Record a destination conversation reference.
        """

        self.conversations[
            canonical_id
        ] = destination_ref

    def record_identity(
        self,
        canonical_id: IdentityKey,
        destination_ref: DestinationIdentityRef,
    ) -> None:
        """
        Record a destination identity reference.
        """

        self.identities[
            canonical_id
        ] = destination_ref

    def record_message(
        self,
        canonical_id: MessageId,
        destination_ref: DestinationMessageRef,
    ) -> None:
        """
        Record a destination message reference.
        """

        self.messages[
            canonical_id
        ] = destination_ref

    def forget_conversation(
        self,
        canonical_id: ConversationId,
    ) -> None:
        """Remove a destination conversation reference after deletion."""

        self.conversations.pop(canonical_id, None)

    def forget_identity(
        self,
        canonical_id: IdentityKey,
    ) -> None:
        """Remove a destination identity reference after deletion."""

        self.identities.pop(canonical_id, None)

    def forget_message(
        self,
        canonical_id: MessageId,
    ) -> None:
        """Remove a destination message reference after deletion."""

        self.messages.pop(canonical_id, None)

    def conversation(
        self,
        canonical_id: ConversationId,
    ) -> DestinationConversationRef:
        """
        Retrieve a destination conversation reference.

        Raises KeyError when the conversation has not been created during
        this execution.
        """

        return self.conversations[
            canonical_id
        ]

    def identity(
        self,
        canonical_id: IdentityKey,
    ) -> DestinationIdentityRef:
        """
        Retrieve a destination identity reference.

        Raises KeyError when the identity has not been created during
        this execution.
        """

        return self.identities[
            canonical_id
        ]

    def message(
        self,
        canonical_id: MessageId,
    ) -> DestinationMessageRef:
        """
        Retrieve a destination message reference.

        Raises KeyError when the message has not been created during
        this execution.
        """

        return self.messages[
            canonical_id
        ]

    def require_conversation(
        self,
        canonical_id: ConversationId,
    ) -> DestinationConversationRef:
        """
        Retrieve a destination conversation reference.

        Raises MissingDestinationReferenceError when the conversation
        has not been created during this execution.
        """

        try:
            return self.conversations[
                canonical_id
            ]
        except KeyError as exc:
            raise MissingDestinationReferenceError(
                "conversation",
                canonical_id,
            ) from exc

    def require_identity(
        self,
        canonical_id: IdentityKey,
    ) -> DestinationIdentityRef:
        """
        Retrieve a destination identity reference.

        Raises MissingDestinationReferenceError when the identity has
        not been created during this execution.
        """

        try:
            return self.identities[
                canonical_id
            ]
        except KeyError as exc:
            raise MissingDestinationReferenceError(
                "identity",
                canonical_id,
            ) from exc

    def require_message(
        self,
        canonical_id: MessageId,
    ) -> DestinationMessageRef:
        """
        Retrieve a destination message reference.

        Raises MissingDestinationReferenceError when the message has
        not been created during this execution.
        """

        try:
            return self.messages[
                canonical_id
            ]
        except KeyError as exc:
            raise MissingDestinationReferenceError(
                "message",
                canonical_id,
            ) from exc