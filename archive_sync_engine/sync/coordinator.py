"""
Synchronization coordinator.

The coordinator does exactly five things:

- Load the current synchronization state.
- Ask the planner for an ordered stream of SyncOperations.
- Execute each operation in order.
- Apply successful execution results to the synchronization state.
- Persist the resulting synchronization state.

It deliberately does not:

- inspect individual operations,
- reorder operations,
- contain destination-specific logic,
- implement planning algorithms,
- implement persistence logic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from archive_sync_engine.archive import Archive
from archive_sync_engine.adapters import (
    DestinationAdapter,
    DestinationCapabilities,
)
from archive_sync_engine.executor import (
    ExecutionContext,
    ExecutionResult,
    OperationExecutor,
)
from archive_sync_engine.operations import SyncOperation
from archive_sync_engine.adapters.exceptions import AuthorizationError
from archive_sync_engine.planner import Planner
from archive_sync_engine.repository import StateRepository

from .synchronization_state import SynchronizationState
from archive_sync_engine.rate_limit import OperationRateLimiter
from .progress import SyncProgress


class SyncCoordinator:
    """
    Coordinates one synchronization run.

    The coordinator orchestrates planning, execution, synchronization
    state updates, and persistence.

    It does not implement planning or execution logic itself.
    """

    def __init__(
        self,
        *,
        archive: Archive,
        planner: Planner,
        executor: OperationExecutor,
        destination: DestinationAdapter,
        capabilities: DestinationCapabilities,
        state_repository: StateRepository,
        between_messages_seconds: float = 0.0,
        between_channels_seconds: float = 0.0,
        rate_limiter: OperationRateLimiter | None = None,
        on_status: Callable[[SyncProgress], None] | None = None,
        compatibility_mode: bool = False,
    ) -> None:
        self._archive = archive
        self._planner = planner
        self._executor = executor
        self._destination = destination
        self._capabilities = capabilities
        self._state_repository = state_repository
        self._on_status = on_status
        self._compatibility_mode = compatibility_mode
        self._rate_limiter = rate_limiter or OperationRateLimiter(
            between_messages_seconds=between_messages_seconds,
            between_channels_seconds=between_channels_seconds,
        )

    def dry_run(self) -> tuple[SyncOperation, ...]:
        """Plan synchronization without executing or persisting anything.

        Dry-run planning loads the current synchronization state and asks the
        Planner for the complete validated operation stream. It deliberately
        does not call the executor, mutate the destination, or persist state.
        """
        synchronization_state: SynchronizationState = (
            self._state_repository.load_synchronization_state()
        )

        return tuple(
            self._planner.plan(
                archive=self._archive,
                synchronization_state=synchronization_state,
                capabilities=self._capabilities,
            )
        )

    def synchronize(self) -> tuple[ExecutionResult, ...]:
        """
        Perform one synchronization run.

        Each operation is executed in the exact order produced by the
        Planner.

        After a successful execution, the resulting destination reference
        is applied to the synchronization state and the complete new state
        is persisted.

        If execution raises an exception, the exception propagates and no
        execution result is recorded for that operation.

        Returns the successful execution results in planner order.
        """

        synchronization_state: SynchronizationState = (
            self._state_repository.load_synchronization_state()
        )

        reconcile_state = getattr(
            self._destination,
            "reconcile_synchronization_state",
            None,
        )
        if reconcile_state is not None:
            repaired_state = reconcile_state(synchronization_state)
            if repaired_state != synchronization_state:
                self._state_repository.save_synchronization_state(repaired_state)
                synchronization_state = repaired_state

        execution_context = ExecutionContext.from_synchronization_state(
            synchronization_state,
        )

        results: list[ExecutionResult] = []

        operations: tuple[SyncOperation, ...] = tuple(
            self._planner.plan(
                archive=self._archive,
                synchronization_state=synchronization_state,
                capabilities=self._capabilities,
            )
        )

        # Static capabilities cannot express every configuration-dependent
        # constraint. Destination preparation must therefore happen before
        # plan validation: preparation may provision destination-local
        # resources (for example, Fluxer custom emojis) that validation needs
        # to resolve reaction operations. Both stages still occur before the
        # first destination mutation.
        validate_operations = getattr(
            self._destination,
            "validate_operations",
            None,
        )

        prepare_archive = getattr(self._destination, "prepare_archive", None)
        prepare_impl = type(self._destination).__dict__.get("prepare_archive")
        if prepare_archive is not None and prepare_impl is not None:
            try:
                custom_emojis = tuple(self._archive.iter_custom_emojis())
            except (AttributeError, TypeError):
                custom_emojis = ()
            if custom_emojis:
                asset_store = getattr(self._executor, "asset_store", None)
                if asset_store is None:
                    raise RuntimeError(
                        "Destination archive preparation requires an AssetStore."
                    )
                prepare_archive(
                    self._archive,
                    asset_store,
                )

        if validate_operations is not None:
            validate_operations(operations)

        previous_channel_id: str | None = None
        seen_message_operation = False
        phase_counts: dict[str, int] = {}

        from archive_sync_engine.operations import (
            CreateConversationOperation, DeleteConversationOperation,
            UpdateConversationOperation, CreateMessageOperation, EditMessageOperation,
            DeleteMessageOperation, PinMessageOperation, UnpinMessageOperation,
            AddAttachmentOperation, RemoveAttachmentOperation, ReorderAttachmentsOperation,
            AddReactionOperation, RemoveReactionOperation, SetMessageReplyOperation,
        )

        for operation in operations:
            phase = _progress_phase(operation)
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
            if self._on_status is not None:
                self._on_status(
                    SyncProgress(
                        phase=phase,
                        current=phase_counts[phase],
                        detail=_progress_detail(operation),
                    )
                )

            channel_id = None
            is_message = isinstance(
                operation,
                (
                    CreateMessageOperation, EditMessageOperation, DeleteMessageOperation,
                    PinMessageOperation, UnpinMessageOperation, AddAttachmentOperation,
                    RemoveAttachmentOperation, ReorderAttachmentsOperation, AddReactionOperation,
                    RemoveReactionOperation, SetMessageReplyOperation,
                ),
            )
            if is_message:
                message = getattr(operation, "message", None)
                channel_id = str(getattr(message, "conversation_id", "")) if message is not None else None

            is_channel = isinstance(
                operation,
                (CreateConversationOperation, UpdateConversationOperation, DeleteConversationOperation),
            )
            if is_channel:
                conversation = getattr(operation, "conversation", None)
                channel_id = str(getattr(conversation, "id", getattr(operation, "conversation_id", "")))

            if channel_id is not None and previous_channel_id is None:
                self._rate_limiter.before_channel()
            elif (
                channel_id is not None
                and previous_channel_id is not None
                and channel_id != previous_channel_id
            ):
                self._rate_limiter.before_channel()

            if is_message:
                if seen_message_operation:
                    self._rate_limiter.before_message()
                seen_message_operation = True

            if channel_id is not None:
                previous_channel_id = channel_id

            try:
                result: ExecutionResult = self._executor.execute(
                    operation=operation,
                    destination=self._destination,
                    context=execution_context,
                )
            except AuthorizationError as exc:
                if not self._compatibility_mode:
                    raise
                canonical_id = _operation_canonical_id(operation)
                result = ExecutionResult(
                    canonical_id=canonical_id,
                    skipped=True,
                    skip_reason=str(exc),
                )

            synchronization_state = (
                synchronization_state.apply_execution_result(
                    canonical_id=result.canonical_id,
                    result=result,
                )
            )

            self._persist_execution_checkpoint(
                operation=operation,
                result=result,
                synchronization_state=synchronization_state,
            )
            results.append(result)

        return tuple(results)

    def _persist_execution_checkpoint(
        self,
        *,
        operation: SyncOperation,
        result: ExecutionResult,
        synchronization_state: SynchronizationState,
    ) -> None:
        """Persist one execution through the repository checkpoint contract."""
        self._state_repository.record_execution(
            operation=operation,
            result=result,
            synchronization_state=synchronization_state,
        )


def _operation_canonical_id(operation: SyncOperation) -> str | None:
    """Return the canonical identifier for a skipped operation."""
    for attribute in ("message", "conversation", "identity"):
        value = getattr(operation, attribute, None)
        if value is not None:
            identifier = getattr(value, "id", getattr(value, "identity_key", None))
            if identifier is not None:
                return str(identifier)
    for attribute in ("message_id", "conversation_id", "identity_key"):
        value = getattr(operation, attribute, None)
        if value is not None:
            return str(value)
    return None


def _progress_phase(operation: SyncOperation) -> str:
    """Map an operation to an adapter-neutral user-facing progress phase."""
    name = type(operation).__name__
    if "Conversation" in name:
        return "conversations"
    if "Identity" in name:
        return "identities"
    if "Attachment" in name:
        return "attachments"
    if "Reaction" in name:
        return "reactions"
    if "Reply" in name:
        return "replies"
    if "Message" in name:
        return "messages"
    return "operations"


def _progress_detail(operation: SyncOperation) -> str | None:
    """Return a safe canonical identifier for a progress event."""
    for attribute in (
        "conversation",
        "identity",
        "message",
        "message_id",
        "identity_key",
        "conversation_id",
    ):
        value = getattr(operation, attribute, None)
        if value is None:
            continue
        if attribute in {"conversation", "identity", "message"}:
            identifier = getattr(value, "id", None) or getattr(
                value, "identity_key", None
            )
            if identifier is not None:
                return str(identifier)
        else:
            return str(value)
    return None
