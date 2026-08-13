"""
Fluxer destination adapter.

This adapter translates canonical Archive Engine operations into Fluxer
operations through the existing fluxer.py-backed Fluxer client.

The adapter contains no synchronization or reconciliation logic.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from archive_sync_engine.adapters.capabilities import DestinationCapabilities
from archive_sync_engine.adapters.destination import DestinationAdapter
from archive_sync_engine.adapters.exceptions import (
    AdapterError,
    CapabilityError,
)
from archive_sync_engine.adapters.references import (
    DestinationAttachmentRef,
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)
from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
    CanonicalReaction,
)


@dataclass(frozen=True, slots=True)
class FluxerIdentityMapping:
    """
    Optional Fluxer masquerade credentials for a canonical identity.

    ``username`` is the canonical identity's source username/name used to
    select the masquerade mapping.

    ``fluxer_auth_key`` is intentionally held only by the adapter/client
    configuration and is never placed into canonical models or state.
    """

    username: str
    fluxer_auth_key: str


class FluxerClientProtocol(Protocol):
    """
    Minimal async surface consumed by the Fluxer adapter.

    The existing ``fluxer_client.py`` implements this surface. Keeping the
    adapter dependent on this small protocol also makes adapter behavior
    independently testable without making the tests depend on fluxer.py.
    """

    async def start(self) -> None:
        ...

    async def close(self) -> None:
        ...

    async def _create_fluxer_channel_from_discord(
        self,
        channel_data: dict[str, Any],
    ) -> Any:
        ...

    async def send_message(
        self,
        channel_id: str,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
        max_retries: int = 3,
        author_name: str | None = None,
        reply_to_id: str | None = None,
    ) -> dict[str, Any] | None:
        ...

    async def edit_message(
        self,
        channel_id: str,
        message_id: str,
        new_content: str,
        new_attachments: list[Any] | None = None,
        max_retries: int = 3,
    ) -> bool:
        ...

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
        max_retries: int = 3,
    ) -> bool:
        ...

    async def delete_channel(
        self,
        channel_id: str,
    ) -> bool:
        ...

    async def apply_reaction(
        self,
        channel_id: str,
        message_id: str,
        emoji: str,
    ) -> bool:
        ...

    async def remove_reaction(
        self,
        channel_id: str,
        message_id: str,
        emoji_id_or_name: str,
        user_id: str = "@me",
    ) -> bool:
        ...

    async def pin_message(
        self,
        channel_id: str,
        message_id: str,
        max_retries: int = 3,
    ) -> bool:
        ...

    async def unpin_message(
        self,
        channel_id: str,
        message_id: str,
        max_retries: int = 3,
    ) -> bool:
        ...


class FluxerDestinationAdapter(DestinationAdapter):
    """
    DestinationAdapter implementation for Fluxer.

    Fluxer conversations are represented by guild channels.

    Identity synchronization is intentionally not advertised as supported:
    the old Fluxer client can masquerade as a mapped user while sending a
    message, but that does not constitute a destination identity object that
    the engine can independently create, update, or delete.

    Likewise, incremental attachment editing and arbitrary attachment
    reordering are not advertised because the existing fluxer.py wrapper
    does not expose those operations.
    """

    _NAME = "fluxer"

    def __init__(
        self,
        client: FluxerClientProtocol,
        *,
        identity_mappings: tuple[FluxerIdentityMapping, ...] = (),
    ) -> None:
        self._client = client
        self._identity_mappings = {
            mapping.username: mapping
            for mapping in identity_mappings
        }

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def capabilities(self) -> DestinationCapabilities:
        return DestinationCapabilities(
            supports_threads=False,
            supports_message_editing=True,
            supports_message_deletion=True,
            supports_conversation_deletion=True,
            supports_message_pinning=True,
            supports_reactions=True,
            supports_custom_emoji=False,
            supports_attachments=True,
            supports_attachment_reordering=False,
            supports_replying=False,
            supports_identity_updates=False,
            supports_identity_deletion=False,
        )

    def create_conversation(
        self,
        conversation: CanonicalConversation,
    ) -> DestinationConversationRef:
        """
        Create a Fluxer guild channel.

        Fluxer does not currently expose a supported thread creation path in
        the existing client, so thread creation is rejected through the
        capability boundary rather than silently flattening the hierarchy.
        """
        if conversation.parent_id is not None:
            raise CapabilityError(
                "FluxerDestinationAdapter does not support thread "
                "conversations."
            )

        channel_type = self._fluxer_channel_type(conversation)

        channel = self._run(
            self._client._create_fluxer_channel_from_discord(
                {
                    "name": conversation.name,
                    "type": channel_type,
                }
            )
        )

        if channel is None:
            raise AdapterError(
                "Fluxer failed to create conversation "
                f"{conversation.id}."
            )

        channel_id = _required_id(
            channel,
            "created Fluxer channel",
        )
        return DestinationConversationRef(channel_id)

    def update_conversation(
        self,
        conversation: CanonicalConversation,
        destination: DestinationConversationRef,
    ) -> None:
        """
        Conversation updates are not yet exposed by the existing Fluxer
        client wrapper.

        Do not silently discard the canonical change.
        """
        raise CapabilityError(
            "Fluxer conversation updates are not implemented by the "
            "current adapter."
        )

    def delete_conversation(
        self,
        destination: DestinationConversationRef,
    ) -> None:
        self._require_success(
            self._run(
                self._client.delete_channel(
                    destination.id,
                )
            ),
            f"delete Fluxer conversation {destination.id}",
        )

    def create_identity(
        self,
        identity: CanonicalIdentity,
    ) -> DestinationIdentityRef:
        raise CapabilityError(
            "Fluxer does not expose independent identity creation through "
            "the current adapter."
        )

    def update_identity(
        self,
        identity: CanonicalIdentity,
        destination: DestinationIdentityRef,
    ) -> None:
        raise CapabilityError(
            "Fluxer identity updates are not supported by the current "
            "adapter."
        )

    def delete_identity(
        self,
        destination: DestinationIdentityRef,
    ) -> None:
        raise CapabilityError(
            "Fluxer identity deletion is not supported by the current "
            "adapter."
        )

    def upload_attachment(
        self,
        attachment: CanonicalAttachment,
        data: bytes,
    ) -> DestinationAttachmentRef:
        """
        Fluxer attachment upload is message-scoped in the current client.

        Standalone attachment upload therefore has no corresponding
        DestinationAdapter operation yet.
        """
        raise CapabilityError(
            "Fluxer does not expose standalone attachment uploads through "
            "the current adapter."
        )

    def add_attachment(
        self,
        message: DestinationMessageRef,
        attachment: CanonicalAttachment,
        data: bytes,
    ) -> DestinationAttachmentRef:
        raise CapabilityError(
            "Fluxer incremental attachment addition is not supported by "
            "the current fluxer.py wrapper."
        )

    def remove_attachment(
        self,
        message: DestinationMessageRef,
        attachment: CanonicalAttachment,
    ) -> None:
        raise CapabilityError(
            "Fluxer incremental attachment removal is not supported by "
            "the current fluxer.py wrapper."
        )

    def reorder_attachments(
        self,
        message: DestinationMessageRef,
        attachments: tuple[CanonicalAttachment, ...],
    ) -> None:
        raise CapabilityError(
            "Fluxer attachment reordering is not supported by the current "
            "adapter."
        )

    def create_message(
        self,
        message: CanonicalMessage,
        destination: DestinationConversationRef,
        attachments: tuple[tuple[CanonicalAttachment, bytes], ...] = (),
    ) -> DestinationMessageRef:
        """
        Create a Fluxer message.

        Reply relationships are deliberately not passed to the underlying
        client here. The current engine models replies as an independent
        operation.
        """
        attachment_payloads = [
            {
                "filename": attachment.filename,
                "data": data,
            }
            for attachment, data in attachments
        ]

        author_name = self._author_name_for(message)

        result = self._run(
            self._client.send_message(
                channel_id=destination.id,
                content=message.content,
                attachments=attachment_payloads or None,
                author_name=author_name,
                reply_to_id=None,
            )
        )

        if result is None:
            raise AdapterError(
                "Fluxer failed to create message "
                f"{message.id} in conversation {destination.id}."
            )

        message_id = _required_id(
            result,
            "created Fluxer message",
        )

        conversation_id = _optional_id(
            result.get("channel_id"),
        ) or destination.id

        return DestinationMessageRef(
            message_id,
            conversation_id=conversation_id,
        )

    def edit_message(
        self,
        message: CanonicalMessage,
        destination: DestinationMessageRef,
    ) -> None:
        conversation_id = self._require_message_conversation(
            destination,
        )

        self._require_success(
            self._run(
                self._client.edit_message(
                    channel_id=conversation_id,
                    message_id=destination.id,
                    new_content=message.content,
                )
            ),
            f"edit Fluxer message {destination.id}",
        )

    def delete_message(
        self,
        destination: DestinationMessageRef,
    ) -> None:
        conversation_id = self._require_message_conversation(
            destination,
        )

        self._require_success(
            self._run(
                self._client.delete_message(
                    channel_id=conversation_id,
                    message_id=destination.id,
                )
            ),
            f"delete Fluxer message {destination.id}",
        )

    def set_message_reply(
        self,
        message: DestinationMessageRef,
        reply_to: DestinationMessageRef | None,
    ) -> None:
        raise CapabilityError(
            "Fluxer reply synchronization is not implemented by the "
            "current adapter."
        )

    def pin_message(
        self,
        message: DestinationMessageRef,
    ) -> None:
        conversation_id = self._require_message_conversation(
            message,
        )

        self._require_success(
            self._run(
                self._client.pin_message(
                    channel_id=conversation_id,
                    message_id=message.id,
                )
            ),
            f"pin Fluxer message {message.id}",
        )

    def unpin_message(
        self,
        message: DestinationMessageRef,
    ) -> None:
        conversation_id = self._require_message_conversation(
            message,
        )

        self._require_success(
            self._run(
                self._client.unpin_message(
                    channel_id=conversation_id,
                    message_id=message.id,
                )
            ),
            f"unpin Fluxer message {message.id}",
        )

    def add_reaction(
        self,
        message: DestinationMessageRef,
        reaction: CanonicalReaction,
    ) -> None:
        if reaction.is_custom:
            raise CapabilityError(
                "Fluxer custom emoji reactions are not supported by the "
                "current adapter."
            )

        conversation_id = self._require_message_conversation(
            message,
        )

        self._require_success(
            self._run(
                self._client.apply_reaction(
                    channel_id=conversation_id,
                    message_id=message.id,
                    emoji=reaction.emoji,
                )
            ),
            f"add reaction to Fluxer message {message.id}",
        )

    def remove_reaction(
        self,
        message: DestinationMessageRef,
        reaction: CanonicalReaction,
    ) -> None:
        if reaction.is_custom:
            raise CapabilityError(
                "Fluxer custom emoji reactions are not supported by the "
                "current adapter."
            )

        conversation_id = self._require_message_conversation(
            message,
        )

        emoji = (
            str(reaction.emoji_id)
            if reaction.emoji_id is not None
            else reaction.emoji
        )

        self._require_success(
            self._run(
                self._client.remove_reaction(
                    channel_id=conversation_id,
                    message_id=message.id,
                    emoji_id_or_name=emoji,
                )
            ),
            f"remove reaction from Fluxer message {message.id}",
        )

    def _author_name_for(
        self,
        message: CanonicalMessage,
    ) -> str | None:
        """
        Resolve an optional Fluxer masquerade username.

        The current engine does not make identity destination mappings part
        of canonical messages. This method therefore uses only an explicit
        adapter configuration mapping and returns None when no mapping is
        configured.

        The exact canonical identity field is intentionally accessed through
        the existing model's ``identity_key`` rather than introducing
        destination-specific data into the canonical model.
        """
        key = str(message.identity_key)
        mapping = self._identity_mappings.get(key)
        if mapping is None:
            return None
        return mapping.username

    @staticmethod
    def _fluxer_channel_type(
        conversation: CanonicalConversation,
    ) -> int:
        """
        Translate the canonical conversation type into the legacy client's
        channel-data contract.

        The existing Fluxer client accepts the Discord-compatible numeric
        values 0=text and 2=voice.
        """
        conversation_type = str(
            getattr(conversation, "type", ""),
        ).lower()

        if conversation_type in {
            "text",
            "guild_text",
            "channel",
        }:
            return 0

        if conversation_type in {
            "voice",
            "guild_voice",
        }:
            return 2

        raise CapabilityError(
            "Fluxer cannot create canonical conversation type "
            f"{conversation_type!r} through the current adapter."
        )

    @staticmethod
    def _require_message_conversation(
        message: DestinationMessageRef,
    ) -> str:
        if message.conversation_id is None:
            raise AdapterError(
                "Fluxer message reference "
                f"{message.id!r} is missing conversation_id."
            )
        return message.conversation_id

    @staticmethod
    def _require_success(
        result: bool,
        action: str,
    ) -> None:
        if not result:
            raise AdapterError(
                f"Fluxer failed to {action}."
            )

    @staticmethod
    def _run(awaitable: Any) -> Any:
        """
        Execute one Fluxer async client operation from the synchronous
        DestinationAdapter boundary.

        The Archive Sync Engine's DestinationAdapter interface is currently
        synchronous, while fluxer.py is asynchronous.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)

        raise RuntimeError(
            "FluxerDestinationAdapter cannot execute from inside a running "
            "asyncio event loop. The synchronous DestinationAdapter boundary "
            "requires an async-to-sync boundary above the adapter."
        )


def _required_id(
    value: Any,
    description: str,
) -> str:
    if isinstance(value, dict):
        identifier = value.get("id")
    else:
        identifier = getattr(value, "id", None)

    if identifier is None:
        raise AdapterError(
            f"Fluxer returned no ID for {description}."
        )

    return str(identifier)


def _optional_id(
    value: Any,
) -> str | None:
    if value is None:
        return None
    return str(value)