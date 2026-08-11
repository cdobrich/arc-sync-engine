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

from dataclasses import replace

from archive_sync_engine.adapters import DestinationAdapter
from archive_sync_engine.asset_store import AssetStore

from archive_sync_engine.executor.context import ExecutionContext
from archive_sync_engine.executor.result import (
    DeletedEntityType,
    ExecutionResult,
)
from archive_sync_engine.operations import (
    AddAttachmentOperation,
    AddReactionOperation,
    CreateConversationOperation,
    CreateIdentityOperation,
    DeleteIdentityOperation,
    CreateMessageOperation,
    DeleteConversationOperation,
    DeleteMessageOperation,
    EditMessageOperation,
    PinMessageOperation,
    RemoveAttachmentOperation,
    ReorderAttachmentsOperation,
    RemoveReactionOperation,
    SetMessageReplyOperation,
    SyncOperation,
    UnpinMessageOperation,
    UpdateConversationOperation,
    UpdateIdentityOperation,
)
from archive_sync_engine.sync.fingerprint import (
    canonical_fingerprint,
    canonical_message_content_fingerprint,
)


class OperationExecutor:
    """
    Execute synchronization operations against a destination.

    OperationExecutor is deliberately small. It translates canonical
    synchronization operations into calls on a DestinationAdapter.

    Attachment operations read canonical bytes from the supplied AssetStore;
    the DestinationAdapter remains responsible for platform-specific upload
    and attachment behavior. Reply operations resolve canonical message IDs
    through the execution-local destination reference context.

    It performs no planning or reconciliation.
    """

    def __init__(
        self,
        *,
        asset_store: AssetStore | None = None,
    ) -> None:
        self._asset_store = asset_store

    def execute(
        self,
        operation: SyncOperation,
        destination: DestinationAdapter,
        context: ExecutionContext | None = None,
    ) -> ExecutionResult:
        """
        Execute one synchronization operation.

        The operation is executed exactly as supplied. No additional
        operations are created and no operations are reordered.
        """

        if context is None:
            context = ExecutionContext()

        match operation:

            case CreateConversationOperation(
                conversation=conversation,
            ):
                destination_ref = (
                    destination.create_conversation(
                        conversation,
                    )
                )

                context.record_conversation(
                    conversation.id,
                    destination_ref,
                )

                return ExecutionResult(
                    canonical_id=str(
                        conversation.id,
                    ),
                    canonical_fingerprint=canonical_fingerprint(
                        conversation,
                    ),
                    conversation_parent_id=(
                        str(conversation.parent_id)
                        if conversation.parent_id is not None
                        else None
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
                    conversation_parent_id=(
                        str(conversation.parent_id)
                        if conversation.parent_id is not None
                        else None
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
                    deleted_entity=DeletedEntityType.CONVERSATION,
                )

            case CreateIdentityOperation(
                identity=identity,
            ):
                destination_ref = (
                    destination.create_identity(
                        identity,
                    )
                )

                context.record_identity(
                    identity.identity_key,
                    destination_ref,
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

            case DeleteIdentityOperation(
                identity_key=identity_key,
            ):
                destination.delete_identity(
                    identity_key,
                )

                return ExecutionResult(
                    canonical_id=str(identity_key),
                    deleted=True,
                    deleted_entity=DeletedEntityType.IDENTITY,
                )

            case CreateMessageOperation(
                message=message,
            ):
                # Initial message creation establishes only the destination
                # message object and its content. Attachments, reactions, pin
                # state, and replies are deliberately reconciled by their
                # dedicated operations so each component has an explicit
                # successful state transition.
                message_for_creation = replace(
                    message,
                    attachments=(),
                    reactions=(),
                    pinned=False,
                    reply_to=None,
                )

                destination_ref = (
                    destination.create_message(
                        message_for_creation,
                    )
                )

                context.record_message(
                    message.id,
                    destination_ref,
                )

                components_pending = bool(
                    message.attachments
                    or message.reactions
                    or message.pinned
                    or message.reply_to is not None
                )

                return ExecutionResult(
                    canonical_id=str(
                        message.id,
                    ),
                    canonical_fingerprint=(
                        None
                        if components_pending
                        else canonical_fingerprint(message)
                    ),
                    message_content_fingerprint=(
                        canonical_message_content_fingerprint(
                            message,
                        )
                    ),
                    message_reactions=(
                        ()
                        if not message.reactions
                        else None
                    ),
                    message_attachments=(
                        ()
                        if not message.attachments
                        else None
                    ),
                    message_pinned=(
                        False
                        if not message.pinned
                        else None
                    ),
                    message_reply_to=(
                        None
                        if message.reply_to is None
                        else None
                    ),
                    message_reply_to_synchronized=(
                        message.reply_to is None
                    ),
                    message=destination_ref,
                )

            case EditMessageOperation(
                message=message,
                canonical_fingerprint=operation_fingerprint,
            ):
                destination.edit_message(
                    message,
                )

                return ExecutionResult(
                    canonical_id=str(
                        message.id,
                    ),
                    canonical_fingerprint=operation_fingerprint,
                    message_content_fingerprint=(
                        canonical_message_content_fingerprint(
                            message,
                        )
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
                    deleted_entity=DeletedEntityType.MESSAGE,
                )

            case AddAttachmentOperation(
                message_id=message_id,
                attachment=attachment,
                resulting_attachments=resulting_attachments,
                canonical_fingerprint=operation_fingerprint,
            ):
                if self._asset_store is None:
                    raise RuntimeError(
                        "AddAttachmentOperation requires an AssetStore."
                    )

                data = self._asset_store.get(
                    attachment.sha256,
                )

                destination.add_attachment(
                    message_id,
                    attachment,
                    data,
                )

                return ExecutionResult(
                    canonical_id=str(message_id),
                    canonical_fingerprint=operation_fingerprint,
                    message_attachments=resulting_attachments,
                )

            case RemoveAttachmentOperation(
                message_id=message_id,
                attachment=attachment,
                resulting_attachments=resulting_attachments,
                canonical_fingerprint=operation_fingerprint,
            ):
                destination.remove_attachment(
                    message_id,
                    attachment,
                )

                return ExecutionResult(
                    canonical_id=str(message_id),
                    canonical_fingerprint=operation_fingerprint,
                    message_attachments=resulting_attachments,
                )

            case ReorderAttachmentsOperation(
                message_id=message_id,
                attachments=attachments,
                canonical_fingerprint=operation_fingerprint,
            ):
                destination.reorder_attachments(
                    message_id,
                    attachments,
                )

                return ExecutionResult(
                    canonical_id=str(message_id),
                    canonical_fingerprint=operation_fingerprint,
                    message_attachments=attachments,
                )

            case SetMessageReplyOperation(
                message_id=message_id,
                reply_to=reply_to,
                canonical_fingerprint=operation_fingerprint,
            ):
                message_ref = context.require_message(
                    message_id,
                )

                reply_ref = (
                    context.require_message(reply_to)
                    if reply_to is not None
                    else None
                )

                destination.set_message_reply(
                    message_ref,
                    reply_ref,
                )

                return ExecutionResult(
                    canonical_id=str(message_id),
                    canonical_fingerprint=operation_fingerprint,
                    message_reply_to=reply_to,
                    message_reply_to_synchronized=True,
                )

            case PinMessageOperation(
                message_id=message_id,
                canonical_fingerprint=operation_fingerprint,
            ):
                destination.pin_message(
                    message_id,
                )

                return ExecutionResult(
                    canonical_id=str(
                        message_id,
                    ),
                    canonical_fingerprint=operation_fingerprint,
                    message_pinned=True,
                )

            case UnpinMessageOperation(
                message_id=message_id,
                canonical_fingerprint=operation_fingerprint,
            ):
                destination.unpin_message(
                    message_id,
                )

                return ExecutionResult(
                    canonical_id=str(
                        message_id,
                    ),
                    canonical_fingerprint=operation_fingerprint,
                    message_pinned=False,
                )

            case AddReactionOperation(
                message_id=message_id,
                reaction=reaction,
                resulting_reactions=resulting_reactions,
                canonical_fingerprint=operation_fingerprint,
            ):
                destination.add_reaction(
                    message_id,
                    reaction,
                )

                return ExecutionResult(
                    canonical_id=str(
                        message_id,
                    ),
                    canonical_fingerprint=operation_fingerprint,
                    message_reactions=resulting_reactions,
                )

            case RemoveReactionOperation(
                message_id=message_id,
                reaction=reaction,
                resulting_reactions=resulting_reactions,
                canonical_fingerprint=operation_fingerprint,
            ):
                destination.remove_reaction(
                    message_id,
                    reaction,
                )

                return ExecutionResult(
                    canonical_id=str(
                        message_id,
                    ),
                    canonical_fingerprint=operation_fingerprint,
                    message_reactions=resulting_reactions,
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