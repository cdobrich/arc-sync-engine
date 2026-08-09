"""
Synchronization planner.

The Planner converts canonical Archive contents into an ordered stream of
SyncOperations.

The current vertical slices support:

    * initial creation;
    * fingerprint-based conversation updates;
    * fingerprint-based identity updates;
    * message content reconciliation;
    * message reaction reconciliation;
    * message pin reconciliation;
    * deletion reconciliation.

Conversation hierarchy is respected.

The Planner does not execute operations or mutate synchronization state.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

from archive_sync_engine.adapters import (
    CapabilityError,
    DestinationCapabilities,
)
from archive_sync_engine.archive import Archive
from archive_sync_engine.models.enums import ConversationType
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
from archive_sync_engine.sync import SynchronizationState
from archive_sync_engine.sync.fingerprint import (
    canonical_fingerprint,
    canonical_message_content_fingerprint,
)

from .plan import SynchronizationPlan


class Planner:
    """
    Produce synchronization operations for an Archive.

    The Planner is deterministic for a given Archive,
    SynchronizationState, and DestinationCapabilities.

    Ordering is dependency-safe:

        parent conversations
            ↓
        child/thread conversations
            ↓
        identities
            ↓
        messages
            ↓
        stale messages
            ↓
        stale child conversations
            ↓
        stale parent conversations
    """

    def plan(
        self,
        archive: Archive,
        synchronization_state: SynchronizationState,
        capabilities: DestinationCapabilities,
    ) -> Iterator[SyncOperation]:
        """
        Produce an ordered stream of synchronization operations.

        Planning is completed before the first operation is yielded. This
        guarantees that capability validation and structural validation are
        complete before a caller can execute any planned operation.

        The returned object remains an iterator so callers retain the
        existing Planner contract, but execution cannot observe a partially
        validated plan.
        """

        operations = tuple(
            self._plan_operations(
                archive=archive,
                synchronization_state=synchronization_state,
                capabilities=capabilities,
            ),
        )

        yield from operations

    def _plan_operations(
        self,
        *,
        archive: Archive,
        synchronization_state: SynchronizationState,
        capabilities: DestinationCapabilities,
    ) -> Iterator[SyncOperation]:
        """
        Build the complete validated operation stream.

        This private generator is fully consumed by :meth:`plan` before
        anything is exposed to the caller.
        """

        conversations = tuple(
            archive.iter_conversations(),
        )

        identities = tuple(
            archive.iter_identities(),
        )

        yield from self._plan_conversations(
            conversations=conversations,
            synchronization_state=synchronization_state,
            capabilities=capabilities,
        )

        yield from self._plan_identities(
            identities=identities,
            synchronization_state=synchronization_state,
            capabilities=capabilities,
        )

        messages = tuple(
            archive.iter_messages(),
        )

        yield from self._plan_messages(
            messages=messages,
            synchronization_state=synchronization_state,
            capabilities=capabilities,
        )

        yield from self._plan_deletions(
            conversations=conversations,
            messages=messages,
            synchronization_state=synchronization_state,
            capabilities=capabilities,
        )

    def build_plan(
        self,
        archive: Archive,
        synchronization_state: SynchronizationState,
        capabilities: DestinationCapabilities,
    ) -> SynchronizationPlan:
        """
        Materialize the planned operations into a SynchronizationPlan.
        """

        return SynchronizationPlan(
            operations=tuple(
                self.plan(
                    archive=archive,
                    synchronization_state=synchronization_state,
                    capabilities=capabilities,
                ),
            ),
        )

    def _plan_conversations(
        self,
        *,
        conversations,
        synchronization_state: SynchronizationState,
        capabilities: DestinationCapabilities,
    ) -> Iterator[SyncOperation]:
        """
        Plan conversation creation or update in dependency-safe order.
        """

        conversations_by_id = {
            conversation.id: conversation
            for conversation in conversations
        }

        processed: set = set()
        visiting: set = set()

        for conversation in conversations:
            yield from self._plan_conversation(
                conversation=conversation,
                conversations_by_id=conversations_by_id,
                synchronization_state=synchronization_state,
                capabilities=capabilities,
                processed=processed,
                visiting=visiting,
            )

    def _plan_conversation(
        self,
        *,
        conversation,
        conversations_by_id,
        synchronization_state,
        capabilities,
        processed,
        visiting,
    ) -> Iterator[SyncOperation]:
        """
        Recursively plan one conversation and its parent dependency.
        """

        conversation_id = conversation.id

        if conversation_id in processed:
            return

        if conversation_id in visiting:
            raise RuntimeError(
                "Circular conversation parent relationship detected "
                f"at {conversation_id}."
            )

        visiting.add(conversation_id)

        if conversation.parent_id is not None:
            parent = conversations_by_id.get(conversation.parent_id)

            if parent is None:
                raise RuntimeError(
                    "Conversation "
                    f"{conversation_id} references missing parent "
                    f"conversation {conversation.parent_id}."
                )

            yield from self._plan_conversation(
                conversation=parent,
                conversations_by_id=conversations_by_id,
                synchronization_state=synchronization_state,
                capabilities=capabilities,
                processed=processed,
                visiting=visiting,
            )

        visiting.remove(conversation_id)
        processed.add(conversation_id)

        canonical_id = str(conversation_id)
        fingerprint = canonical_fingerprint(conversation)

        if canonical_id not in synchronization_state.conversations:
            if conversation.conversation_type == ConversationType.THREAD:
                self._require_capability(
                    capabilities.supports_threads,
                    "supports_threads",
                    "create thread conversations",
                )

            yield CreateConversationOperation(
                conversation=conversation,
            )
            return

        previous_fingerprint = (
            synchronization_state.conversation_fingerprints.get(
                canonical_id,
            )
        )

        if previous_fingerprint is None:
            raise RuntimeError(
                "Synchronization state is missing the canonical fingerprint "
                f"for conversation {canonical_id}."
            )

        if previous_fingerprint != fingerprint:
            if conversation.conversation_type == ConversationType.THREAD:
                self._require_capability(
                    capabilities.supports_threads,
                    "supports_threads",
                    "update thread conversations",
                )

            yield UpdateConversationOperation(
                conversation=conversation,
            )

    def _plan_identities(
        self,
        *,
        identities,
        synchronization_state: SynchronizationState,
        capabilities: DestinationCapabilities,
    ) -> Iterator[SyncOperation]:
        """
        Plan identity creation or update.
        """

        for identity in identities:
            identity_key = str(identity.identity_key)
            fingerprint = canonical_fingerprint(identity)

            if identity_key not in synchronization_state.identities:
                yield CreateIdentityOperation(
                    identity=identity,
                )
                continue

            previous_fingerprint = (
                synchronization_state.identity_fingerprints.get(
                    identity_key,
                )
            )

            if previous_fingerprint is None:
                raise RuntimeError(
                    "Synchronization state is missing the canonical fingerprint "
                    f"for identity {identity_key}."
                )

            if previous_fingerprint != fingerprint:
                self._require_capability(
                    capabilities.supports_identity_updates,
                    "supports_identity_updates",
                    "update identities",
                )

                yield UpdateIdentityOperation(
                    identity=identity,
                )

    def _plan_messages(
        self,
        *,
        messages,
        synchronization_state: SynchronizationState,
        capabilities: DestinationCapabilities,
    ) -> Iterator[SyncOperation]:
        """
        Plan message creation and component-level reconciliation.

        A message fingerprint includes content, reactions, and pin state.
        Those components are deliberately decomposed into their own
        operations so that a reaction or pin change does not become an
        EditMessageOperation.

        Existing synchronized messages must have a complete component
        baseline in SynchronizationState. Missing required state is an
        invalid current synchronization state and raises rather than
        silently planning against incomplete synchronization metadata.
        """

        for message in messages:
            message_id = str(message.id)
            fingerprint = canonical_fingerprint(message)

            if message_id not in synchronization_state.messages:
                yield CreateMessageOperation(
                    message=message,
                )
                continue

            previous_fingerprint = (
                synchronization_state.message_fingerprints.get(
                    message_id,
                )
            )

            if previous_fingerprint is None:
                raise RuntimeError(
                    "Synchronization state is missing the canonical fingerprint "
                    f"for message {message_id}."
                )

            if message_id not in synchronization_state.message_content_fingerprints:
                raise RuntimeError(
                    "Synchronization state is missing the message content "
                    f"fingerprint for message {message_id}."
                )

            if message_id not in synchronization_state.message_reactions:
                raise RuntimeError(
                    "Synchronization state is missing the reaction baseline "
                    f"for message {message_id}."
                )

            if message_id not in synchronization_state.message_pinned:
                raise RuntimeError(
                    "Synchronization state is missing the pin baseline "
                    f"for message {message_id}."
                )

            previous_content_fingerprint = (
                synchronization_state.message_content_fingerprints[message_id]
            )
            previous_reactions = synchronization_state.message_reactions[
                message_id
            ]
            previous_pinned = synchronization_state.message_pinned[message_id]

            current_content_fingerprint = (
                canonical_message_content_fingerprint(message)
            )
            current_reactions = tuple(message.reactions)
            current_pinned = message.pinned

            content_changed = (
                previous_content_fingerprint
                != current_content_fingerprint
            )
            reactions_changed = previous_reactions != current_reactions
            pinned_changed = previous_pinned != current_pinned

            if not (
                content_changed
                or reactions_changed
                or pinned_changed
            ):
                if previous_fingerprint != fingerprint:
                    raise RuntimeError(
                        "Synchronization state for message "
                        f"{message_id} has an inconsistent canonical fingerprint."
                    )

                continue

            operations: list[SyncOperation] = []

            if content_changed:
                self._require_capability(
                    capabilities.supports_message_editing,
                    "supports_message_editing",
                    "edit messages",
                )

                operations.append(
                    EditMessageOperation(
                        message=message,
                    ),
                )

            if reactions_changed:
                self._require_capability(
                    capabilities.supports_reactions,
                    "supports_reactions",
                    "reconcile message reactions",
                )

            working_reactions = list(previous_reactions)

            for reaction in previous_reactions:
                if reaction in current_reactions:
                    continue

                working_reactions.remove(reaction)

                operations.append(
                    RemoveReactionOperation(
                        message_id=message.id,
                        reaction=reaction,
                        resulting_reactions=tuple(working_reactions),
                    ),
                )

            for reaction in current_reactions:
                if reaction in previous_reactions:
                    continue

                working_reactions.append(reaction)

                operations.append(
                    AddReactionOperation(
                        message_id=message.id,
                        reaction=reaction,
                        resulting_reactions=tuple(working_reactions),
                    ),
                )

            if pinned_changed:
                self._require_capability(
                    capabilities.supports_message_pinning,
                    "supports_message_pinning",
                    "change message pin state",
                )

                if current_pinned:
                    operations.append(
                        PinMessageOperation(
                            message_id=message.id,
                        ),
                    )
                else:
                    operations.append(
                        UnpinMessageOperation(
                            message_id=message.id,
                        ),
                    )

            if not operations:
                raise RuntimeError(
                    "Message reconciliation produced no operation despite "
                    f"detected changes for message {message_id}."
                )

            operations[-1] = self._mark_message_operation_complete(
                operation=operations[-1],
                canonical_fingerprint=fingerprint,
            )

            yield from operations

    @staticmethod
    def _mark_message_operation_complete(
        *,
        operation: SyncOperation,
        canonical_fingerprint: str,
    ) -> SyncOperation:
        """
        Mark the final message-state operation as completing the full
        canonical message baseline.
        """

        return replace(
            operation,
            canonical_fingerprint=canonical_fingerprint,
        )

    @staticmethod
    def _require_capability(
        supported: bool,
        capability_name: str,
        action: str,
    ) -> None:
        """
        Reject a synchronization plan that requires an unsupported feature.

        The Planner must never emit an operation that the supplied
        destination capabilities say cannot be performed. Silently skipping
        such an operation would leave SynchronizationState permanently
        behind the canonical Archive and cause the same work to be planned
        again on every synchronization run.
        """

        if supported:
            return

        raise CapabilityError(
            f"Destination capability {capability_name!r} is required to "
            f"{action}."
        )

    def _plan_deletions(
        self,
        *,
        conversations,
        messages,
        synchronization_state: SynchronizationState,
        capabilities: DestinationCapabilities,
    ) -> Iterator[SyncOperation]:
        """
        Plan deletion of destination entities absent from the Archive.

        Messages are deleted before conversations because messages depend
        on their containing conversations.

        Conversations are deleted child-first. SynchronizationState retains
        each conversation's parent relationship so this remains possible
        after the conversation disappears from the Archive.
        """

        archive_message_ids = {
            str(message.id)
            for message in messages
        }

        for message_id in synchronization_state.messages:
            if message_id not in archive_message_ids:
                self._require_capability(
                    capabilities.supports_message_deletion,
                    "supports_message_deletion",
                    "delete messages",
                )

                yield DeleteMessageOperation(
                    message_id=message_id,
                )

        archive_conversation_ids = {
            str(conversation.id)
            for conversation in conversations
        }

        stale_conversation_ids = {
            conversation_id
            for conversation_id in synchronization_state.conversations
            if conversation_id not in archive_conversation_ids
        }

        yield from self._plan_stale_conversations(
            stale_conversation_ids=stale_conversation_ids,
            synchronization_state=synchronization_state,
            capabilities=capabilities,
        )

    def _plan_stale_conversations(
        self,
        *,
        stale_conversation_ids: set[str],
        synchronization_state: SynchronizationState,
        capabilities: DestinationCapabilities,
    ) -> Iterator[SyncOperation]:
        """
        Emit stale conversations in child-before-parent order.
        """

        processed: set[str] = set()
        visiting: set[str] = set()

        children_by_parent: dict[str, list[str]] = {}

        for conversation_id in stale_conversation_ids:
            if conversation_id not in synchronization_state.conversation_parent_ids:
                raise RuntimeError(
                    "Synchronization state is missing the parent relationship "
                    f"for stale conversation {conversation_id}."
                )

            parent_id = synchronization_state.conversation_parent_ids[
                conversation_id
            ]

            if parent_id in stale_conversation_ids:
                children_by_parent.setdefault(
                    parent_id,
                    [],
                ).append(
                    conversation_id,
                )

        for conversation_id in synchronization_state.conversations:
            if conversation_id not in stale_conversation_ids:
                continue

            yield from self._plan_stale_conversation(
                conversation_id=conversation_id,
                synchronization_state=synchronization_state,
                children_by_parent=children_by_parent,
                processed=processed,
                visiting=visiting,
                capabilities=capabilities,
            )

    def _plan_stale_conversation(
        self,
        *,
        conversation_id: str,
        synchronization_state: SynchronizationState,
        children_by_parent: dict[str, list[str]],
        processed: set[str],
        visiting: set[str],
        capabilities: DestinationCapabilities,
    ) -> Iterator[SyncOperation]:
        """
        Recursively emit a stale conversation after its stale children.
        """

        if conversation_id in processed:
            return

        if conversation_id in visiting:
            raise RuntimeError(
                "Circular synchronization-state conversation hierarchy "
                f"detected at {conversation_id}."
            )

        visiting.add(conversation_id)

        for child_id in children_by_parent.get(
            conversation_id,
            [],
        ):
            yield from self._plan_stale_conversation(
                conversation_id=child_id,
                synchronization_state=synchronization_state,
                children_by_parent=children_by_parent,
                processed=processed,
                visiting=visiting,
                capabilities=capabilities,
            )

        visiting.remove(conversation_id)
        processed.add(conversation_id)

        self._require_capability(
            capabilities.supports_conversation_deletion,
            "supports_conversation_deletion",
            "delete conversations",
        )

        yield DeleteConversationOperation(
            conversation_id=conversation_id,
        )
