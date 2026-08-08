"""
Synchronization planner.

The Planner converts canonical Archive contents into an ordered stream
of SyncOperations.

The current vertical slice supports:

    * initial creation;
    * conversation updates;
    * identity updates;
    * message edits.

Conversation hierarchy is respected.

The Planner does not execute operations or mutate synchronization state.
"""

from __future__ import annotations

from collections.abc import Iterator

from archive_sync_engine.adapters import DestinationCapabilities
from archive_sync_engine.archive import Archive
from archive_sync_engine.operations import (
    CreateConversationOperation,
    CreateIdentityOperation,
    CreateMessageOperation,
    EditMessageOperation,
    SyncOperation,
    UpdateConversationOperation,
    UpdateIdentityOperation,
)
from archive_sync_engine.sync import SynchronizationState
from archive_sync_engine.sync.fingerprint import canonical_fingerprint

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
    """

    def plan(
        self,
        archive: Archive,
        synchronization_state: SynchronizationState,
        capabilities: DestinationCapabilities,
    ) -> Iterator[SyncOperation]:
        """
        Produce an ordered stream of synchronization operations.

        Existing entities are reconciled using their recorded canonical
        fingerprints.

        Destination capabilities are currently part of the Planner
        contract but are not yet required for the operations supported by
        this slice.
        """

        yield from self._plan_conversations(
            archive=archive,
            synchronization_state=synchronization_state,
            capabilities=capabilities,
        )

        yield from self._plan_identities(
            archive=archive,
            synchronization_state=synchronization_state,
        )

        yield from self._plan_messages(
            archive=archive,
            synchronization_state=synchronization_state,
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
        archive: Archive,
        synchronization_state: SynchronizationState,
        capabilities: DestinationCapabilities,
    ) -> Iterator[SyncOperation]:
        """
        Plan conversation creation or update in dependency-safe order.

        Parent conversations are always considered before their child
        threads.

        An existing conversation is updated only when its canonical
        fingerprint differs from the recorded fingerprint.

        A destination conversation without a recorded fingerprint is
        treated as existing but unknown and is not updated by this slice.
        """

        del capabilities

        conversations = tuple(
            archive.iter_conversations(),
        )

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
                processed=processed,
                visiting=visiting,
            )

    def _plan_conversation(
        self,
        *,
        conversation,
        conversations_by_id,
        synchronization_state,
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

        visiting.add(
            conversation_id,
        )

        if conversation.parent_id is not None:

            parent = conversations_by_id.get(
                conversation.parent_id,
            )

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
                processed=processed,
                visiting=visiting,
            )

        visiting.remove(
            conversation_id,
        )

        processed.add(
            conversation_id,
        )

        canonical_id = str(
            conversation_id,
        )

        fingerprint = canonical_fingerprint(
            conversation,
        )

        if canonical_id not in synchronization_state.conversations:

            yield CreateConversationOperation(
                conversation=conversation,
            )

            return

        previous_fingerprint = (
            synchronization_state.conversation_fingerprints.get(
                canonical_id,
            )
        )

        if (
            previous_fingerprint is not None
            and previous_fingerprint != fingerprint
        ):
            yield UpdateConversationOperation(
                conversation=conversation,
            )

    def _plan_identities(
        self,
        *,
        archive: Archive,
        synchronization_state: SynchronizationState,
    ) -> Iterator[SyncOperation]:
        """
        Plan identity creation or update.

        Existing identities are updated only when their canonical
        fingerprint differs from the recorded fingerprint.
        """

        for identity in archive.iter_identities():

            identity_key = str(
                identity.identity_key,
            )

            fingerprint = canonical_fingerprint(
                identity,
            )

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

            if (
                previous_fingerprint is not None
                and previous_fingerprint != fingerprint
            ):
                yield UpdateIdentityOperation(
                    identity=identity,
                )

    def _plan_messages(
        self,
        *,
        archive: Archive,
        synchronization_state: SynchronizationState,
    ) -> Iterator[SyncOperation]:
        """
        Plan message creation or editing.

        Existing messages are edited only when their canonical
        fingerprint differs from the recorded fingerprint.

        Reaction and pin reconciliation are intentionally deferred to
        their own vertical slices.
        """

        for message in archive.iter_messages():

            message_id = str(
                message.id,
            )

            fingerprint = canonical_fingerprint(
                message,
            )

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

            if (
                previous_fingerprint is not None
                and previous_fingerprint != fingerprint
            ):
                yield EditMessageOperation(
                    message=message,
                )