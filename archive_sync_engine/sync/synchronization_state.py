"""
Synchronization state.

A SynchronizationState is an immutable snapshot of the synchronization
metadata required by the Planner to compute synchronization work.

The state records destination references and the canonical fingerprints
last successfully synchronized for those references.

For messages, the state also records the independent canonical baselines
for editable content, reactions, and pin state. This allows the Planner to
decompose a message fingerprint difference into the appropriate operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)
from archive_sync_engine.executor.result import (
    DeletedEntityType,
    ExecutionResult,
)
from archive_sync_engine.models import CanonicalAttachment, CanonicalReaction
from archive_sync_engine.models.ids import MessageId


@dataclass(frozen=True, slots=True)
class SynchronizationState:
    """
    Transition-immutable synchronization snapshot.

    State changes use functional transitions: every ``with_*`` or
    ``without_*`` method returns a new snapshot and leaves the existing
    snapshot unchanged. The mappings stored by the snapshot are treated as
    read-only by contract; callers must not mutate them in place.

    Destination references identify corresponding destination objects.

    Fingerprints identify canonical state successfully synchronized for
    each corresponding object.

    Message component baselines are part of the current state contract:
    every fully synchronized message has content, reaction, attachment,
    pin, and reply baselines. A newly created message may temporarily
    omit any component baseline whose dedicated synchronization operation
    has not yet succeeded. The complete message fingerprint is absent
    until all required component baselines have been established.

    Conversation parent relationships are retained because the canonical
    parent may no longer be present in the Archive when a conversation is
    deleted. They are required for child-before-parent deletion ordering.

    Persistence invariants for the current state representation are:

    * every conversation fingerprint and parent entry has a conversation
      destination mapping;
    * every identity fingerprint has an identity destination mapping;
    * every message component baseline and full message fingerprint has a
      message destination mapping;
    * every synchronized message has a content baseline;
    * a message with a full fingerprint has reaction, attachment, pin, and
      reply baselines as well;
    * a reply baseline may be absent for a partial message, but when present
      its target must also be a synchronized message; and
    * a partial message must not have a full message fingerprint.

    Conversation parent IDs are allowed to refer to a conversation that is
    no longer synchronized because stale parent information is intentionally
    retained for deletion ordering.
    """

    conversations: dict[
        str,
        DestinationConversationRef,
    ] = field(default_factory=dict)

    identities: dict[
        str,
        DestinationIdentityRef,
    ] = field(default_factory=dict)

    messages: dict[
        str,
        DestinationMessageRef,
    ] = field(default_factory=dict)

    conversation_fingerprints: dict[
        str,
        str,
    ] = field(default_factory=dict)

    conversation_parent_ids: dict[
        str,
        str | None,
    ] = field(default_factory=dict)

    identity_fingerprints: dict[
        str,
        str,
    ] = field(default_factory=dict)

    message_fingerprints: dict[
        str,
        str,
    ] = field(default_factory=dict)

    message_content_fingerprints: dict[
        str,
        str,
    ] = field(default_factory=dict)

    message_reactions: dict[
        str,
        tuple[CanonicalReaction, ...],
    ] = field(default_factory=dict)

    message_attachments: dict[
        str,
        tuple[CanonicalAttachment, ...],
    ] = field(default_factory=dict)

    message_pinned: dict[
        str,
        bool,
    ] = field(default_factory=dict)

    message_reply_to: dict[
        str,
        MessageId | None,
    ] = field(default_factory=dict)

    def with_conversation(
        self,
        canonical_id: str,
        destination_ref: DestinationConversationRef,
        fingerprint: str,
        parent_id: str | None,
    ) -> SynchronizationState:
        """
        Return a new state containing a synchronized conversation.
        """

        conversations = dict(self.conversations)
        conversations[canonical_id] = destination_ref

        fingerprints = dict(self.conversation_fingerprints)
        fingerprints[canonical_id] = fingerprint

        parent_ids = dict(self.conversation_parent_ids)
        parent_ids[canonical_id] = parent_id

        return SynchronizationState(
            conversations=conversations,
            identities=dict(self.identities),
            messages=dict(self.messages),
            conversation_fingerprints=fingerprints,
            conversation_parent_ids=parent_ids,
            identity_fingerprints=dict(self.identity_fingerprints),
            message_fingerprints=dict(self.message_fingerprints),
            message_content_fingerprints=dict(
                self.message_content_fingerprints,
            ),
            message_reactions=dict(self.message_reactions),
            message_attachments=dict(self.message_attachments),
            message_pinned=dict(self.message_pinned),
            message_reply_to=dict(self.message_reply_to),
        )

    def with_identity(
        self,
        identity_key: str,
        destination_ref: DestinationIdentityRef,
        fingerprint: str,
    ) -> SynchronizationState:
        """
        Return a new state containing a synchronized identity.
        """

        identities = dict(self.identities)
        identities[identity_key] = destination_ref

        fingerprints = dict(self.identity_fingerprints)
        fingerprints[identity_key] = fingerprint

        return SynchronizationState(
            conversations=dict(self.conversations),
            identities=identities,
            messages=dict(self.messages),
            conversation_fingerprints=dict(self.conversation_fingerprints),
            conversation_parent_ids=dict(self.conversation_parent_ids),
            identity_fingerprints=fingerprints,
            message_fingerprints=dict(self.message_fingerprints),
            message_content_fingerprints=dict(
                self.message_content_fingerprints,
            ),
            message_reactions=dict(self.message_reactions),
            message_attachments=dict(self.message_attachments),
            message_pinned=dict(self.message_pinned),
            message_reply_to=dict(self.message_reply_to),
        )

    def with_message(
        self,
        canonical_id: str,
        destination_ref: DestinationMessageRef,
        fingerprint: str,
        content_fingerprint: str,
        reactions: tuple[CanonicalReaction, ...] | None,
        attachments: tuple[CanonicalAttachment, ...] | None,
        pinned: bool | None,
        reply_to: MessageId | None = None,
    ) -> SynchronizationState:
        """
        Return a new state containing a fully synchronized message.
        """

        messages = dict(self.messages)
        messages[canonical_id] = destination_ref

        fingerprints = dict(self.message_fingerprints)
        fingerprints[canonical_id] = fingerprint

        content_fingerprints = dict(self.message_content_fingerprints)
        content_fingerprints[canonical_id] = content_fingerprint

        message_reactions = dict(self.message_reactions)
        if reactions is not None:
            message_reactions[canonical_id] = tuple(reactions)

        message_attachments = dict(self.message_attachments)
        if attachments is not None:
            message_attachments[canonical_id] = tuple(attachments)

        message_pinned = dict(self.message_pinned)
        if pinned is not None:
            message_pinned[canonical_id] = pinned

        message_reply_to = dict(self.message_reply_to)
        message_reply_to[canonical_id] = reply_to

        return SynchronizationState(
            conversations=dict(self.conversations),
            identities=dict(self.identities),
            messages=messages,
            conversation_fingerprints=dict(self.conversation_fingerprints),
            conversation_parent_ids=dict(self.conversation_parent_ids),
            identity_fingerprints=dict(self.identity_fingerprints),
            message_fingerprints=fingerprints,
            message_content_fingerprints=content_fingerprints,
            message_reactions=message_reactions,
            message_attachments=message_attachments,
            message_pinned=message_pinned,
            message_reply_to=message_reply_to,
        )

    def with_message_pinned(
        self,
        canonical_id: str,
        pinned: bool,
    ) -> SynchronizationState:
        """Return a new state with only one message pin baseline updated."""
        if canonical_id not in self.messages:
            raise KeyError(
                f"Cannot update pin baseline for unknown message {canonical_id!r}."
            )

        message_pinned = dict(self.message_pinned)
        message_pinned[canonical_id] = pinned

        return SynchronizationState(
            conversations=dict(self.conversations),
            identities=dict(self.identities),
            messages=dict(self.messages),
            conversation_fingerprints=dict(self.conversation_fingerprints),
            conversation_parent_ids=dict(self.conversation_parent_ids),
            identity_fingerprints=dict(self.identity_fingerprints),
            message_fingerprints=dict(self.message_fingerprints),
            message_content_fingerprints=dict(self.message_content_fingerprints),
            message_reactions=dict(self.message_reactions),
            message_attachments=dict(self.message_attachments),
            message_pinned=message_pinned,
            message_reply_to=dict(self.message_reply_to),
        )

    def without_conversation(
        self,
        canonical_id: str,
    ) -> SynchronizationState:
        """
        Return a new state without a synchronized conversation.
        """

        conversations = dict(self.conversations)
        conversations.pop(canonical_id, None)

        fingerprints = dict(self.conversation_fingerprints)
        fingerprints.pop(canonical_id, None)

        parent_ids = dict(self.conversation_parent_ids)
        parent_ids.pop(canonical_id, None)

        return SynchronizationState(
            conversations=conversations,
            identities=dict(self.identities),
            messages=dict(self.messages),
            conversation_fingerprints=fingerprints,
            conversation_parent_ids=parent_ids,
            identity_fingerprints=dict(self.identity_fingerprints),
            message_fingerprints=dict(self.message_fingerprints),
            message_content_fingerprints=dict(
                self.message_content_fingerprints,
            ),
            message_reactions=dict(self.message_reactions),
            message_attachments=dict(self.message_attachments),
            message_pinned=dict(self.message_pinned),
            message_reply_to=dict(self.message_reply_to),
        )

    def without_messages_for_conversation(
        self,
        conversation_id: str,
    ) -> SynchronizationState:
        """Return state with all destination message mappings for a conversation removed."""
        message_ids = {
            canonical_id
            for canonical_id, reference in self.messages.items()
            if reference.conversation_id == conversation_id
        }
        if not message_ids:
            return self

        messages = {
            key: value for key, value in self.messages.items()
            if key not in message_ids
        }
        fingerprints = {
            key: value for key, value in self.message_fingerprints.items()
            if key not in message_ids
        }
        content_fingerprints = {
            key: value for key, value in self.message_content_fingerprints.items()
            if key not in message_ids
        }
        reactions = {
            key: value for key, value in self.message_reactions.items()
            if key not in message_ids
        }
        attachments = {
            key: value for key, value in self.message_attachments.items()
            if key not in message_ids
        }
        pinned = {
            key: value for key, value in self.message_pinned.items()
            if key not in message_ids
        }
        replies = {
            key: (None if reply_to is not None and str(reply_to) in message_ids else reply_to)
            for key, reply_to in self.message_reply_to.items()
            if key not in message_ids
        }

        return SynchronizationState(
            conversations=dict(self.conversations),
            identities=dict(self.identities),
            messages=messages,
            conversation_fingerprints=dict(self.conversation_fingerprints),
            conversation_parent_ids=dict(self.conversation_parent_ids),
            identity_fingerprints=dict(self.identity_fingerprints),
            message_fingerprints=fingerprints,
            message_content_fingerprints=content_fingerprints,
            message_reactions=reactions,
            message_attachments=attachments,
            message_pinned=pinned,
            message_reply_to=replies,
        )

    def without_message(
        self,
        canonical_id: str,
    ) -> SynchronizationState:
        """
        Return a new state without a synchronized message.
        """

        messages = dict(self.messages)
        messages.pop(canonical_id, None)

        fingerprints = dict(self.message_fingerprints)
        fingerprints.pop(canonical_id, None)

        content_fingerprints = dict(self.message_content_fingerprints)
        content_fingerprints.pop(canonical_id, None)

        message_reactions = dict(self.message_reactions)
        message_reactions.pop(canonical_id, None)

        message_attachments = dict(self.message_attachments)
        message_attachments.pop(canonical_id, None)

        message_pinned = dict(self.message_pinned)
        message_pinned.pop(canonical_id, None)

        message_reply_to = dict(self.message_reply_to)
        message_reply_to.pop(canonical_id, None)

        dangling_replyers = sorted(
            message_id
            for message_id, reply_to in message_reply_to.items()
            if reply_to is not None and str(reply_to) == canonical_id
        )
        if dangling_replyers:
            raise ValueError(
                "Cannot remove message "
                f"{canonical_id!r} while synchronized messages "
                "still reference it as a reply target: "
                + ", ".join(dangling_replyers)
                + "."
            )

        return SynchronizationState(
            conversations=dict(self.conversations),
            identities=dict(self.identities),
            messages=messages,
            conversation_fingerprints=dict(self.conversation_fingerprints),
            conversation_parent_ids=dict(self.conversation_parent_ids),
            identity_fingerprints=dict(self.identity_fingerprints),
            message_fingerprints=fingerprints,
            message_content_fingerprints=content_fingerprints,
            message_reactions=message_reactions,
            message_attachments=message_attachments,
            message_pinned=message_pinned,
            message_reply_to=message_reply_to,
        )

    def without_identity(
        self,
        canonical_id: str,
    ) -> SynchronizationState:
        """
        Return a new state without a synchronized identity.
        """

        identities = dict(self.identities)
        identities.pop(canonical_id, None)

        fingerprints = dict(self.identity_fingerprints)
        fingerprints.pop(canonical_id, None)

        return SynchronizationState(
            conversations=dict(self.conversations),
            identities=identities,
            messages=dict(self.messages),
            conversation_fingerprints=dict(self.conversation_fingerprints),
            conversation_parent_ids=dict(self.conversation_parent_ids),
            identity_fingerprints=fingerprints,
            message_fingerprints=dict(self.message_fingerprints),
            message_content_fingerprints=dict(
                self.message_content_fingerprints,
            ),
            message_reactions=dict(self.message_reactions),
            message_attachments=dict(self.message_attachments),
            message_pinned=dict(self.message_pinned),
            message_reply_to=dict(self.message_reply_to),
        )

    def _with_partial_message(
        self,
        *,
        canonical_id: str,
        destination_ref: DestinationMessageRef,
        content_fingerprint: str,
        reactions: tuple[CanonicalReaction, ...] | None,
        attachments: tuple[CanonicalAttachment, ...] | None,
        pinned: bool | None,
        reply_to: MessageId | None,
        reply_to_synchronized: bool,
    ) -> SynchronizationState:
        """Record a newly created message with only completed baselines."""

        messages = dict(self.messages)
        messages[canonical_id] = destination_ref

        content_fingerprints = dict(self.message_content_fingerprints)
        content_fingerprints[canonical_id] = content_fingerprint

        message_reactions = dict(self.message_reactions)
        if reactions is not None:
            message_reactions[canonical_id] = tuple(reactions)

        message_attachments = dict(self.message_attachments)
        if attachments is not None:
            message_attachments[canonical_id] = tuple(attachments)

        message_pinned = dict(self.message_pinned)
        if pinned is not None:
            message_pinned[canonical_id] = pinned

        message_reply_to = dict(self.message_reply_to)
        if reply_to_synchronized:
            message_reply_to[canonical_id] = reply_to

        fingerprints = dict(self.message_fingerprints)
        fingerprints.pop(canonical_id, None)

        return SynchronizationState(
            conversations=dict(self.conversations),
            identities=dict(self.identities),
            messages=messages,
            conversation_fingerprints=dict(self.conversation_fingerprints),
            conversation_parent_ids=dict(self.conversation_parent_ids),
            identity_fingerprints=dict(self.identity_fingerprints),
            message_fingerprints=fingerprints,
            message_content_fingerprints=content_fingerprints,
            message_reactions=message_reactions,
            message_attachments=message_attachments,
            message_pinned=message_pinned,
            message_reply_to=message_reply_to,
        )

    def apply_execution_result(
        self,
        canonical_id: str | None,
        result: ExecutionResult,
    ) -> SynchronizationState:
        """
        Return a new state containing the result of successful execution.
        """

        if canonical_id is None:
            return self

        if result.skipped:
            if result.deleted or any((
                result.conversation is not None,
                result.identity is not None,
                result.message is not None,
            )):
                raise ValueError("Skipped ExecutionResult cannot mutate synchronization state.")
            return self

        if result.deleted:
            if result.deleted_entity is None:
                raise ValueError(
                    "Deleted ExecutionResult must identify its entity type."
                )

            if (
                result.conversation is not None
                or result.identity is not None
                or result.message is not None
            ):
                raise ValueError(
                    "Deleted ExecutionResult cannot contain "
                    "destination references."
                )

            if result.deleted_entity is DeletedEntityType.CONVERSATION:
                return self.without_conversation(canonical_id)

            if result.deleted_entity is DeletedEntityType.MESSAGE:
                return self.without_message(canonical_id)

            if result.deleted_entity is DeletedEntityType.IDENTITY:
                return self.without_identity(canonical_id)

            raise ValueError(
                f"Unsupported deleted entity type: {result.deleted_entity!r}"
            )

        references = (
            result.conversation is not None,
            result.identity is not None,
            result.message is not None,
        )

        if sum(references) > 1:
            raise ValueError(
                "ExecutionResult cannot contain multiple destination "
                "references."
            )

        if result.conversation is not None:
            if result.canonical_fingerprint is None:
                raise ValueError(
                    "Conversation execution results require a canonical "
                    "fingerprint."
                )

            return self.with_conversation(
                canonical_id=canonical_id,
                destination_ref=result.conversation,
                fingerprint=result.canonical_fingerprint,
                parent_id=result.conversation_parent_id,
            )

        if result.identity is not None:
            if result.canonical_fingerprint is None:
                raise ValueError(
                    "Identity execution results require a canonical "
                    "fingerprint."
                )

            return self.with_identity(
                identity_key=canonical_id,
                destination_ref=result.identity,
                fingerprint=result.canonical_fingerprint,
            )

        if result.message is not None:
            if result.message_content_fingerprint is None:
                raise ValueError(
                    "Message creation results require a message content "
                    "fingerprint."
                )

            if result.canonical_fingerprint is None:
                return self._with_partial_message(
                    canonical_id=canonical_id,
                    destination_ref=result.message,
                    content_fingerprint=result.message_content_fingerprint,
                    reactions=result.message_reactions,
                    attachments=result.message_attachments,
                    pinned=result.message_pinned,
                    reply_to=result.message_reply_to,
                    reply_to_synchronized=result.message_reply_to_synchronized,
                )

            if (
                result.message_reactions is None
                or result.message_attachments is None
                or result.message_pinned is None
            ):
                raise ValueError(
                    "A complete message creation result requires all message "
                    "component baselines."
                )

            if not result.message_reply_to_synchronized:
                raise ValueError(
                    "A complete message creation result must record the "
                    "reply baseline."
                )

            return self.with_message(
                canonical_id=canonical_id,
                destination_ref=result.message,
                fingerprint=result.canonical_fingerprint,
                content_fingerprint=result.message_content_fingerprint,
                reactions=result.message_reactions,
                attachments=result.message_attachments,
                pinned=result.message_pinned,
                reply_to=result.message_reply_to,
            )

        has_message_component_update = (
            any(
                value is not None
                for value in (
                    result.message_content_fingerprint,
                    result.message_reactions,
                    result.message_attachments,
                    result.message_pinned,
                )
            )
            or result.message_reply_to_synchronized
        )

        if not has_message_component_update:
            if result.canonical_fingerprint is not None:
                raise ValueError(
                    "A message canonical fingerprint cannot be recorded "
                    "without a message reference or component baseline update."
                )

            return self

        if canonical_id not in self.messages:
            raise ValueError(
                "Message component execution results require an existing "
                f"synchronized message {canonical_id}."
            )

        if result.canonical_fingerprint is not None:
            missing_baselines = []

            if (
                canonical_id not in self.message_content_fingerprints
                and result.message_content_fingerprint is None
            ):
                missing_baselines.append("content")

            if (
                canonical_id not in self.message_reactions
                and result.message_reactions is None
            ):
                missing_baselines.append("reactions")

            if (
                canonical_id not in self.message_attachments
                and result.message_attachments is None
            ):
                missing_baselines.append("attachments")

            if (
                canonical_id not in self.message_pinned
                and result.message_pinned is None
            ):
                missing_baselines.append("pin")

            if (
                canonical_id not in self.message_reply_to
                and not result.message_reply_to_synchronized
            ):
                missing_baselines.append("reply")

            if missing_baselines:
                raise ValueError(
                    "A complete message canonical fingerprint cannot be "
                    "recorded while message baselines are missing: "
                    + ", ".join(missing_baselines)
                    + "."
                )

        if result.message_content_fingerprint is not None:
            content_fingerprints = dict(self.message_content_fingerprints)
            content_fingerprints[canonical_id] = (
                result.message_content_fingerprint
            )
        else:
            content_fingerprints = dict(self.message_content_fingerprints)

        if result.message_reactions is not None:
            message_reactions = dict(self.message_reactions)
            message_reactions[canonical_id] = tuple(
                result.message_reactions,
            )
        else:
            message_reactions = dict(self.message_reactions)

        if result.message_attachments is not None:
            message_attachments = dict(self.message_attachments)
            message_attachments[canonical_id] = tuple(
                result.message_attachments,
            )
        else:
            message_attachments = dict(self.message_attachments)

        if result.message_pinned is not None:
            message_pinned = dict(self.message_pinned)
            message_pinned[canonical_id] = result.message_pinned
        else:
            message_pinned = dict(self.message_pinned)

        if result.message_reply_to_synchronized:
            message_reply_to = dict(self.message_reply_to)
            message_reply_to[canonical_id] = result.message_reply_to
        else:
            message_reply_to = dict(self.message_reply_to)

        fingerprints = dict(self.message_fingerprints)

        if result.canonical_fingerprint is not None:
            fingerprints[canonical_id] = result.canonical_fingerprint

        return SynchronizationState(
            conversations=dict(self.conversations),
            identities=dict(self.identities),
            messages=dict(self.messages),
            conversation_fingerprints=dict(self.conversation_fingerprints),
            conversation_parent_ids=dict(self.conversation_parent_ids),
            identity_fingerprints=dict(self.identity_fingerprints),
            message_fingerprints=fingerprints,
            message_content_fingerprints=content_fingerprints,
            message_reactions=message_reactions,
            message_attachments=message_attachments,
            message_pinned=message_pinned,
            message_reply_to=message_reply_to,
        )
