from __future__ import annotations

from archive_sync_engine.adapters import DestinationAdapter
from archive_sync_engine.executor.result import ExecutionResult
from archive_sync_engine.operations import (
    CreateConversationOperation,
    SyncOperation,
)


class DefaultOperationExecutor:
    """
    Default synchronization executor.
    """

    def execute(
        self,
        operation: SyncOperation,
        destination: DestinationAdapter,
    ) -> ExecutionResult:

        match operation:

            case CreateConversationOperation(conversation=conversation):

                destination_ref = (
                    destination.create_conversation(
                        conversation,
                    )
                )

                return ExecutionResult(
                    conversation=destination_ref,
                )

            case _:

                raise NotImplementedError(
                    f"Unsupported operation: "
                    f"{type(operation).__name__}"
                )