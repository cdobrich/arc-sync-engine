"""
Synchronization operation executor.

OperationExecutor consumes SyncOperations produced by the Planner
and applies them to a DestinationAdapter.

The executor is responsible only for execution.

It does not:

    * traverse an Archive;
    * create synchronization plans;
    * reorder operations;
    * reconcile canonical state;
    * make capability decisions; or
    * persist synchronization state.

Operations are executed exactly in the order received.
"""

from __future__ import annotations

from archive_sync_engine.adapters import DestinationAdapter
from archive_sync_engine.executor.result import ExecutionResult
from archive_sync_engine.operations import (
    AddReactionOperation,
    CreateConversationOperation,
    CreateIdentityOperation,
    CreateMessageOperation,
    DeleteConversationOperation,
    DeleteMessageOperation,
    EditMessageOperation,
    PinMessageOperation,
    RemoveReactionOperation,
    SyncOperation,
    UnpinMessageOperation,
    UpdateConversationOperation,
    UpdateIdentityOperation,
)


class OperationExecutor:
    """
    Execute synchronization operations against a destination.
    """

    def execute(
        self,
        operation: SyncOperation,
        destination: DestinationAdapter,
    ) -> ExecutionResult:
        """
        Execute one synchronization operation.

        The operation is executed exactly as supplied. The executor
        performs no planning or reordering.
        """

        match operation:

            case CreateConversationOperation(
                conversation=conversation,
            ):
                destination_ref = (
                    destination.create_conversation(
                        conversation,
                    )
                )

                return ExecutionResult(
                    canonical_id=str(
                        conversation.id,
                    ),
                    conversation=destination_ref,
                )

            case UpdateConversationOperation(
                conversation=conversation,
            ):
                destination.update_conversation(
                    conversation,
                )

                return ExecutionResult(
                    canonical_id=str(
                        conversation.id,
                    ),
                )

            case DeleteConversationOperation(
                conversation_id=conversation_id,
            ):
                destination.delete_conversation(
                    conversation_id,
                )

                return ExecutionResult(
                    canonical_id=str(
                        conversation_id,
                    ),
                )

            case CreateIdentityOperation(
                identity=identity,
            ):
                destination_ref = (
                    destination.create_identity(
                        identity,
                    )
                )

                return ExecutionResult(
                    canonical_id=str(
                        identity.identity_key,
                    ),
                    identity=destination_ref,
                )

            case UpdateIdentityOperation(
                identity=identity,
            ):
                destination.update_identity(
                    identity,
                )

                return ExecutionResult(
                    canonical_id=str(
                        identity.identity_key,
                    ),
                )

            case CreateMessageOperation(
                message=message,
            ):
                destination_ref = (
                    destination.create_message(
                        message,
                    )
                )

                return ExecutionResult(
                    canonical_id=str(
                        message.id,
                    ),
                    message=destination_ref,
                )

            case EditMessageOperation(
                message=message,
            ):
                destination.edit_message(
                    message,
                )

                return ExecutionResult(
                    canonical_id=str(
                        message.id,
                    ),
                )

            case DeleteMessageOperation(
                message_id=message_id,
            ):
                destination.delete_message(
                    message_id,
                )

                return ExecutionResult(
                    canonical_id=str(
                        message_id,
                    ),
                )

            case PinMessageOperation(
                message_id=message_id,
            ):
                destination.pin_message(
                    message_id,
                )

                return ExecutionResult(
                    canonical_id=str(
                        message_id,
                    ),
                )

            case UnpinMessageOperation(
                message_id=message_id,
            ):
                destination.unpin_message(
                    message_id,
                )

                return ExecutionResult(
                    canonical_id=str(
                        message_id,
                    ),
                )

            case AddReactionOperation(
                message_id=message_id,
                reaction=reaction,
            ):
                destination.add_reaction(
                    message_id,
                    reaction,
                )

                return ExecutionResult(
                    canonical_id=str(
                        message_id,
                    ),
                )

            case RemoveReactionOperation(
                message_id=message_id,
                reaction=reaction,
            ):
                destination.remove_reaction(
                    message_id,
                    reaction,
                )

                return ExecutionResult(
                    canonical_id=str(
                        message_id,
                    ),
                )

            case _:
                raise NotImplementedError(
                    "Unsupported operation: "
                    f"{type(operation).__name__}"
                )