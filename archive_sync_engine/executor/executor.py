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

from collections.abc import Iterable

from archive_sync_engine.adapters import DestinationAdapter
from archive_sync_engine.executor.context import ExecutionContext
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
from archive_sync_engine.sync.fingerprint import canonical_fingerprint


class OperationExecutor:
    """
    Execute synchronization operations against a destination.

    OperationExecutor is deliberately small. It translates canonical
    synchronization operations into calls on a DestinationAdapter.

    It performs no planning or reconciliation.
    """

    def execute(
        self,
        operation: SyncOperation,
        destination: DestinationAdapter,
    ) -> ExecutionResult:
        """
        Execute one synchronization operation.

        The operation is executed exactly as supplied. No additional
        operations are created and no operations are reordered.
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
                    canonical_fingerprint=canonical_fingerprint(
                        conversation,
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
                    canonical_fingerprint=canonical_fingerprint(
                        conversation,
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
                    deleted=True,
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
                    canonical_fingerprint=canonical_fingerprint(
                        identity,
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
                    canonical_fingerprint=canonical_fingerprint(
                        identity,
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
                    canonical_fingerprint=canonical_fingerprint(
                        message,
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
                    canonical_fingerprint=canonical_fingerprint(
                        message,
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
                    deleted=True,
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

    def execute_all(
        self,
        operations: Iterable[SyncOperation],
        destination: DestinationAdapter,
    ) -> tuple[
        ExecutionContext,
        tuple[ExecutionResult, ...],
    ]:
        """
        Execute an ordered sequence of synchronization operations.

        Operations are consumed and executed in exactly the order
        supplied by the caller.

        Destination references created during execution are retained in
        one execution-local context.

        The context is intentionally not persisted and is discarded when
        execution completes.
        """

        context = ExecutionContext()

        results: list[ExecutionResult] = []

        for operation in operations:

            result = self.execute(
                operation,
                destination,
            )

            self._record_result(
                operation,
                result,
                context,
            )

            results.append(
                result,
            )

        return (
            context,
            tuple(
                results,
            ),
        )

    @staticmethod
    def _record_result(
        operation: SyncOperation,
        result: ExecutionResult,
        context: ExecutionContext,
    ) -> None:
        """
        Record destination references produced by an operation.

        Only creation operations produce destination references at this
        stage. Other operation results are intentionally not recorded.
        """

        match operation:

            case CreateConversationOperation(
                conversation=conversation,
            ):
                if result.conversation is None:
                    raise RuntimeError(
                        "CreateConversationOperation did not produce "
                        "a destination conversation reference."
                    )

                context.record_conversation(
                    conversation.id,
                    result.conversation,
                )

            case CreateIdentityOperation(
                identity=identity,
            ):
                if result.identity is None:
                    raise RuntimeError(
                        "CreateIdentityOperation did not produce "
                        "a destination identity reference."
                    )

                context.record_identity(
                    identity.identity_key,
                    result.identity,
                )

            case CreateMessageOperation(
                message=message,
            ):
                if result.message is None:
                    raise RuntimeError(
                        "CreateMessageOperation did not produce "
                        "a destination message reference."
                    )

                context.record_message(
                    message.id,
                    result.message,
                )

            case _:
                return