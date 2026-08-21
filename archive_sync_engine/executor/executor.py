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

    @property
    def asset_store(self) -> AssetStore | None:
        """Return the content-addressed archive asset store, when configured."""
        return self._asset_store

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
                destination_ref = context.require_conversation(
                    conversation.id,
                )
                destination.update_conversation(
                    conversation,
                    destination_ref,
                )

                return ExecutionResult(
                    canonical_id=str(
                        conversation.id,
                    ),
                    canonical_fingerprint=canonical_fingerprint(
                        conversation,
                    ),
                    conversation=destination_ref,
                    conversation_parent_id=(
                        str(conversation.parent_id)
                        if conversation.parent_id is not None
                        else None
                    ),
                )

            case DeleteConversationOperation(
                conversation_id=conversation_id,
            ):
                destination_ref = context.require_conversation(
                    conversation_id,
                )
                destination.delete_conversation(
                    destination_ref,
                )

                context.forget_conversation(
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
                destination_ref = context.require_identity(
                    identity.identity_key,
                )
                destination.update_identity(
                    identity,
                    destination_ref,
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
                destination_ref = context.require_identity(
                    identity_key,
                )
                destination.delete_identity(
                    destination_ref,
                )

                context.forget_identity(
                    identity_key,
                )

                return ExecutionResult(
                    canonical_id=str(identity_key),
                    deleted=True,
                    deleted_entity=DeletedEntityType.IDENTITY,
                )

            case CreateMessageOperation(
                message=message,
                include_attachments=include_attachments,
                include_reply_to=include_reply_to,
            ):
                attachment_payloads: tuple[tuple[CanonicalAttachment, bytes], ...] = ()
                if include_attachments and message.attachments:
                    if self._asset_store is None:
                        raise RuntimeError(
                            "CreateMessageOperation with initial attachments "
                            "requires an AssetStore."
                        )

                    attachment_payloads = tuple(
                        (
                            attachment,
                            self._asset_store.get(attachment.sha256),
                        )
                        for attachment in message.attachments
                    )

                reply_ref = (
                    context.require_message(message.reply_to)
                    if include_reply_to and message.reply_to is not None
                    else None
                )

                message_for_creation = replace(
                    message,
                    attachments=(message.attachments if include_attachments else ()),
                    reactions=(),
                    pinned=False,
                    reply_to=None,
                )

                conversation_ref = context.require_conversation(
                    message.conversation_id,
                )

                if include_attachments:
                    if include_reply_to:
                        destination_ref = destination.create_message(
                            message_for_creation,
                            conversation_ref,
                            attachment_payloads,
                            reply_to=reply_ref,
                        )
                    else:
                        destination_ref = destination.create_message(
                            message_for_creation,
                            conversation_ref,
                            attachment_payloads,
                        )
                elif include_reply_to:
                    destination_ref = destination.create_message(
                        message_for_creation,
                        conversation_ref,
                        reply_to=reply_ref,
                    )
                else:
                    destination_ref = destination.create_message(
                        message_for_creation,
                        conversation_ref,
                    )

                context.record_message(
                    message.id,
                    destination_ref,
                )

                components_pending = bool(
                    (message.attachments and not include_attachments)
                    or message.reactions
                    or message.pinned
                    or (message.reply_to is not None and not include_reply_to)
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
                        tuple(message.attachments)
                        if include_attachments
                        else (() if not message.attachments else None)
                    ),
                    message_pinned=(
                        False
                        if not message.pinned
                        else None
                    ),
                    message_reply_to=(
                        message.reply_to
                        if include_reply_to
                        else None
                    ),
                    message_reply_to_synchronized=(
                        message.reply_to is None or include_reply_to
                    ),
                    message=destination_ref,
                )

            case EditMessageOperation(
                message=message,
                canonical_fingerprint=operation_fingerprint,
            ):
                destination_ref = context.require_message(
                    message.id,
                )
                destination.edit_message(
                    message,
                    destination_ref,
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
                destination_ref = context.require_message(
                    message_id,
                )

                destination.delete_message(
                    destination_ref,
                )

                context.forget_message(
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

                destination_ref = context.require_message(
                    message_id,
                )

                destination.add_attachment(
                    destination_ref,
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
                destination_ref = context.require_message(
                    message_id,
                )

                destination.remove_attachment(
                    destination_ref,
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
                destination_ref = context.require_message(
                    message_id,
                )

                destination.reorder_attachments(
                    destination_ref,
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
                destination_ref = context.require_message(
                    message_id,
                )

                destination.pin_message(
                    destination_ref,
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
                destination_ref = context.require_message(
                    message_id,
                )

                destination.unpin_message(
                    destination_ref,
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
                destination_ref = context.require_message(
                    message_id,
                )

                destination.add_reaction(
                    destination_ref,
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
                destination_ref = context.require_message(
                    message_id,
                )

                destination.remove_reaction(
                    destination_ref,
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
                context=context,
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