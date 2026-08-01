"""
Destination execution engine.

OperationExecutor applies destination operations against a canonical
Archive.

The OperationExecutor owns orchestration of destination-side archive
operations. It does not interpret platform-specific behavior; that
responsibility belongs to DestinationAdapter.

The initial vertical slice supports creation of:

    conversations
        ↓
    messages

Destination references are retained as part of the execution result so
later synchronization phases can resolve canonical objects to their
destination counterparts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from archive_sync_engine.adapters import DestinationAdapter
from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
    DestinationMessageRef,
)
from archive_sync_engine.models.ids import (
    ConversationId,
    MessageId,
)

if TYPE_CHECKING:
    from archive_sync_engine.archive.archive import Archive


@dataclass(frozen=True, slots=True)
class ArchiveExecutionResult:
    """
    Result of executing one complete archive against a destination.

    Canonical identifiers remain separate from destination references.
    """

    conversations: dict[
        ConversationId,
        DestinationConversationRef,
    ] = field(
        default_factory=dict,
    )

    messages: dict[
        MessageId,
        DestinationMessageRef,
    ] = field(
        default_factory=dict,
    )


class OperationExecutor:
    """
    Execute destination operations against an Archive.

    The first vertical slice creates every canonical conversation and
    every canonical message in deterministic archive order.
    """

    def execute(
        self,
        archive: Archive,
        destination: DestinationAdapter,
    ) -> ArchiveExecutionResult:
        """
        Export canonical archive contents to the destination.

        Conversations are created before their messages.

        Messages are created in the same deterministic order exposed by
        the Archive.
        """

        conversations: dict[
            ConversationId,
            DestinationConversationRef,
        ] = {}

        messages: dict[
            MessageId,
            DestinationMessageRef,
        ] = {}

        for conversation in archive.iter_conversations():

            conversation_ref = (
                destination.create_conversation(
                    conversation,
                )
            )

            conversations[
                conversation.id
            ] = conversation_ref

            for message in archive.iter_messages_for_conversation(
                conversation.id,
            ):
                message_ref = (
                    destination.create_message(
                        message,
                    )
                )

                messages[
                    message.id
                ] = message_ref

        return ArchiveExecutionResult(
            conversations=conversations,
            messages=messages,
        )