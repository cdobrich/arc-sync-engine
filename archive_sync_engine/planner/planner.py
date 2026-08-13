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
    * message attachment reconciliation;
    * deletion reconciliation for messages, conversations, and identities.

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
            identities=identities,
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
            self._require_capability(
                capabilities.supports_conversation_updates,
                "supports_conversation_updates",
                "update conversations",
            )

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
                self._require_capability(
                    capabilities.supports_identity_creation,
                    "supports_identity_creation",
                    "create identities",
                )
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

        Content, attachments, reactions, pin state, and reply relationships
        are independently synchronized. Reply operations are deferred until
        after all message operations have been planned so execution-local
        destination references exist for replies to messages created during
        the same synchronization run.
        """

        message_ids = {str(message.id) for message in messages}
        stale_message_ids = set(synchronization_state.messages) - message_ids

        for message in messages:
            if message.reply_to is not None:
                reply_id = str(message.reply_to)
                if reply_id not in message_ids or reply_id in stale_message_ids:
                    raise RuntimeError(
                        "Message "
                        f"{message.id} references reply target {message.reply_to} "
                        "that is not present in the canonical Archive."
                    )

        reply_operations: list[SyncOperation] = []

        for message in messages:
            message_id = str(message.id)
            fingerprint = canonical_fingerprint(message)

            if message_id not in synchronization_state.messages:
                # Message creation establishes only the destination message
                # object and canonical content. Component state is reconciled
                # through the same dedicated operations used for existing
                # messages so AssetStore-backed attachments, reactions, pins,
                # and replies cannot be marked synchronized prematurely.
                include_initial_attachments = False
                include_initial_reply = False
                component_operations: list[SyncOperation] = []

                if message.attachments:
                    if capabilities.supports_initial_message_attachments:
                        include_initial_attachments = True
                    else:
                        self._require_capability(
                            capabilities.supports_attachments,
                            "supports_attachments",
                            "reconcile message attachments",
                        )

                        working_attachments: list = []
                        for attachment in message.attachments:
                            working_attachments.append(attachment)
                            component_operations.append(
                                AddAttachmentOperation(
                                    message_id=message.id,
                                    attachment=attachment,
                                    resulting_attachments=(
                                        tuple(working_attachments)
                                    ),
                                ),
                            )

                if message.reactions:
                    self._require_capability(
                        capabilities.supports_reactions,
                        "supports_reactions",
                        "reconcile message reactions",
                    )

                    if any(reaction.is_custom for reaction in message.reactions):
                        self._require_capability(
                            capabilities.supports_custom_emoji,
                            "supports_custom_emoji",
                            "reconcile custom emoji reactions",
                        )

                    working_reactions: list = []
                    for reaction in message.reactions:
                        working_reactions.append(reaction)
                        component_operations.append(
                            AddReactionOperation(
                                message_id=message.id,
                                reaction=reaction,
                                resulting_reactions=(
                                    tuple(working_reactions)
                                ),
                            ),
                        )

                if message.pinned:
                    self._require_capability(
                        capabilities.supports_message_pinning,
                        "supports_message_pinning",
                        "change message pin state",
                    )
                    component_operations.append(
                        PinMessageOperation(
                            message_id=message.id,
                        ),
                    )

                if message.reply_to is not None:
                    reply_target_id = str(message.reply_to)
                    if (
                        capabilities.supports_initial_message_replying
                        and reply_target_id in synchronization_state.messages
                    ):
                        include_initial_reply = True
                    else:
                        self._require_capability(
                            capabilities.supports_replying,
                            "supports_replying",
                            "set message replies",
                        )
                        reply_operations.append(
                            SetMessageReplyOperation(
                                message_id=message.id,
                                reply_to=message.reply_to,
                                canonical_fingerprint=fingerprint,
                            ),
                        )

                if component_operations:
                    if message.reply_to is None or include_initial_reply:
                        component_operations[-1] = self._mark_message_operation_complete(
                            operation=component_operations[-1],
                            canonical_fingerprint=fingerprint,
                        )
                    yield CreateMessageOperation(
                        message=message,
                        include_attachments=include_initial_attachments,
                        include_reply_to=include_initial_reply,
                    )
                    yield from component_operations
                else:
                    yield CreateMessageOperation(
                        message=message,
                        include_attachments=include_initial_attachments,
                        include_reply_to=include_initial_reply,
                    )

                continue

            previous_fingerprint = synchronization_state.message_fingerprints.get(
                message_id,
            )

            if message_id not in synchronization_state.message_content_fingerprints:
                raise RuntimeError(
                    "Synchronization state is missing the message content "
                    f"fingerprint for message {message_id}."
                )

            # A message without a complete fingerprint can be a legitimate
            # partial synchronization snapshot left by a failed initial
            # component operation. Missing component baselines therefore mean
            # that the component has not yet been established and should be
            # reconciled from its empty destination baseline. Once the full
            # fingerprint exists, all component baselines are mandatory.
            if previous_fingerprint is not None:
                if message_id not in synchronization_state.message_reactions:
                    raise RuntimeError(
                        "Synchronization state is missing the reaction baseline "
                        f"for message {message_id}."
                    )

                if message_id not in synchronization_state.message_attachments:
                    raise RuntimeError(
                        "Synchronization state is missing the attachment baseline "
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
            previous_reactions = synchronization_state.message_reactions.get(
                message_id,
                (),
            )
            previous_attachments = synchronization_state.message_attachments.get(
                message_id,
                (),
            )
            previous_pinned = synchronization_state.message_pinned.get(
                message_id,
                False,
            )

            current_content_fingerprint = canonical_message_content_fingerprint(
                message,
            )
            current_reactions = tuple(message.reactions)
            current_attachments = tuple(message.attachments)
            current_pinned = message.pinned

            reply_baseline_present = message_id in synchronization_state.message_reply_to
            previous_reply_to = synchronization_state.message_reply_to.get(message_id)

            if previous_fingerprint is not None and not reply_baseline_present:
                raise RuntimeError(
                    "Synchronization state is missing the reply baseline "
                    f"for message {message_id}."
                )

            content_changed = (
                previous_content_fingerprint != current_content_fingerprint
            )
            reactions_changed = previous_reactions != current_reactions
            attachments_changed = previous_attachments != current_attachments
            pinned_changed = previous_pinned != current_pinned
            reply_changed = (
                not reply_baseline_present
                or previous_reply_to != message.reply_to
            )

            if not (
                content_changed
                or reactions_changed
                or attachments_changed
                or pinned_changed
                or reply_changed
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
                operations.append(EditMessageOperation(message=message))

            if reactions_changed:
                self._require_capability(
                    capabilities.supports_reactions,
                    "supports_reactions",
                    "reconcile message reactions",
                )

                changed_reactions = tuple(
                    reaction
                    for reaction in previous_reactions
                    if reaction not in current_reactions
                ) + tuple(
                    reaction
                    for reaction in current_reactions
                    if reaction not in previous_reactions
                )

                if any(reaction.is_custom for reaction in changed_reactions):
                    self._require_capability(
                        capabilities.supports_custom_emoji,
                        "supports_custom_emoji",
                        "reconcile custom emoji reactions",
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

            if attachments_changed:
                self._require_capability(
                    capabilities.supports_attachments,
                    "supports_attachments",
                    "reconcile message attachments",
                )

            working_attachments = list(previous_attachments)
            for attachment in previous_attachments:
                if attachment in current_attachments:
                    continue
                working_attachments.remove(attachment)
                operations.append(
                    RemoveAttachmentOperation(
                        message_id=message.id,
                        attachment=attachment,
                        resulting_attachments=tuple(working_attachments),
                    ),
                )

            for attachment in current_attachments:
                if attachment in previous_attachments:
                    continue
                working_attachments.append(attachment)
                operations.append(
                    AddAttachmentOperation(
                        message_id=message.id,
                        attachment=attachment,
                        resulting_attachments=tuple(working_attachments),
                    ),
                )

            if attachments_changed and tuple(working_attachments) != current_attachments:
                self._require_capability(
                    capabilities.supports_attachment_reordering,
                    "supports_attachment_reordering",
                    "reorder message attachments",
                )
                operations.append(
                    ReorderAttachmentsOperation(
                        message_id=message.id,
                        attachments=current_attachments,
                    ),
                )

            if pinned_changed:
                self._require_capability(
                    capabilities.supports_message_pinning,
                    "supports_message_pinning",
                    "change message pin state",
                )
                operations.append(
                    PinMessageOperation(message_id=message.id)
                    if current_pinned
                    else UnpinMessageOperation(message_id=message.id)
                )

            if reply_changed:
                self._require_capability(
                    capabilities.supports_replying,
                    "supports_replying",
                    "set message replies",
                )
                reply_operations.append(
                    SetMessageReplyOperation(
                        message_id=message.id,
                        reply_to=message.reply_to,
                        canonical_fingerprint=fingerprint,
                    ),
                )

            if operations:
                if reply_changed:
                    yield from operations
                else:
                    operations[-1] = self._mark_message_operation_complete(
                        operation=operations[-1],
                        canonical_fingerprint=fingerprint,
                    )
                    yield from operations

        yield from reply_operations

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
        identities,
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

        stale_message_ids = {
            message_id
            for message_id in synchronization_state.messages
            if message_id not in archive_message_ids
        }

        yield from self._plan_stale_messages(
            stale_message_ids=stale_message_ids,
            synchronization_state=synchronization_state,
            capabilities=capabilities,
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

        archive_identity_keys = {
            str(identity.identity_key)
            for identity in identities
        }

        stale_identity_keys = {
            identity_key
            for identity_key in synchronization_state.identities
            if identity_key not in archive_identity_keys
        }

        referenced_identity_keys = {
            str(message.identity_key)
            for message in messages
        }

        invalid_identity_references = (
            stale_identity_keys & referenced_identity_keys
        )
        if invalid_identity_references:
            raise RuntimeError(
                "Canonical Archive messages reference identities that are "
                "missing from the Archive identity set: "
                + ", ".join(sorted(invalid_identity_references))
                + "."
            )

        for identity_key in stale_identity_keys:
            if identity_key not in archive_identity_keys:
                self._require_capability(
                    capabilities.supports_identity_deletion,
                    "supports_identity_deletion",
                    "delete identities",
                )

                yield DeleteIdentityOperation(
                    identity_key=identity_key,
                )

    def _plan_stale_messages(
        self,
        *,
        stale_message_ids: set[str],
        synchronization_state: SynchronizationState,
        capabilities: DestinationCapabilities,
    ) -> Iterator[SyncOperation]:
        """
        Emit stale messages in reply-dependency-safe order.

        When a stale message replies to another stale message, the replying
        message must be deleted first so the destination never has to retain
        a reply relationship pointing at a message that has already been
        removed. The persisted reply baseline is the only synchronization
        metadata consulted here; the Archive is authoritative for messages
        that still exist.
        """

        children_by_parent: dict[str, list[str]] = {}

        for message_id in synchronization_state.messages:
            if message_id not in stale_message_ids:
                continue

            reply_to = synchronization_state.message_reply_to.get(message_id)

            if reply_to is None:
                continue

            parent_id = str(reply_to)
            if parent_id in stale_message_ids:
                children_by_parent.setdefault(
                    parent_id,
                    [],
                ).append(
                    message_id,
                )

        processed: set[str] = set()
        visiting: set[str] = set()

        for message_id in synchronization_state.messages:
            if message_id not in stale_message_ids:
                continue

            yield from self._plan_stale_message(
                message_id=message_id,
                children_by_parent=children_by_parent,
                processed=processed,
                visiting=visiting,
                capabilities=capabilities,
            )

    def _plan_stale_message(
        self,
        *,
        message_id: str,
        children_by_parent: dict[str, list[str]],
        processed: set[str],
        visiting: set[str],
        capabilities: DestinationCapabilities,
    ) -> Iterator[SyncOperation]:
        """
        Recursively emit a stale message after its stale reply children.
        """

        if message_id in processed:
            return

        if message_id in visiting:
            raise RuntimeError(
                "Circular synchronization-state message reply relationship "
                f"detected at {message_id}."
            )

        visiting.add(message_id)

        for child_id in children_by_parent.get(
            message_id,
            [],
        ):
            yield from self._plan_stale_message(
                message_id=child_id,
                children_by_parent=children_by_parent,
                processed=processed,
                visiting=visiting,
                capabilities=capabilities,
            )

        visiting.remove(message_id)
        processed.add(message_id)

        self._require_capability(
            capabilities.supports_message_deletion,
            "supports_message_deletion",
            "delete messages",
        )

        yield DeleteMessageOperation(
            message_id=message_id,
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
