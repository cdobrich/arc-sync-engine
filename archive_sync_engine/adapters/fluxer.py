"""Fluxer destination adapter.

This adapter translates canonical Archive-Sync Engine operations into calls to
an injected Fluxer client wrapper. It contains no synchronization or planning
logic. Unsupported destination features are rejected explicitly rather than
silently discarded.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from archive_sync_engine.adapters.capabilities import DestinationCapabilities
from archive_sync_engine.adapters.destination import DestinationAdapter
from archive_sync_engine.adapters.exceptions import AdapterError, CapabilityError
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
    """Optional Fluxer masquerade mapping for a canonical identity."""

    username: str
    fluxer_auth_key: str


class FluxerClientProtocol(Protocol):
    """Minimal async client surface required by the Fluxer adapter."""

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

    async def delete_channel(self, channel_id: str) -> bool:
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
    """Destination adapter for the currently supported Fluxer API surface."""

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
            supports_conversation_updates=False,
            supports_message_deletion=True,
            supports_conversation_deletion=True,
            supports_message_pinning=True,
            supports_reactions=True,
            supports_custom_emoji=False,
            supports_attachments=False,
            supports_attachment_reordering=False,
            supports_replying=False,
            supports_identity_creation=False,
            supports_identity_updates=False,
            supports_identity_deletion=False,
        )

    def create_conversation(
        self,
        conversation: CanonicalConversation,
    ) -> DestinationConversationRef:
        if conversation.parent_id is not None:
            raise CapabilityError(
                "Fluxer does not support thread conversations through the "
                "current adapter."
            )

        channel_type = self._fluxer_channel_type(conversation)
        name = conversation.title or str(conversation.id)
        result = self._run(
            self._client._create_fluxer_channel_from_discord(
                {
                    "name": name,
                    "type": channel_type,
                }
            )
        )

        channel_id = _required_id(result, "created Fluxer channel")
        return DestinationConversationRef(channel_id)

    def update_conversation(
        self,
        conversation: CanonicalConversation,
        destination: DestinationConversationRef,
    ) -> None:
        raise CapabilityError(
            "Fluxer conversation updates are not supported by the current "
            "client wrapper."
        )

    def delete_conversation(
        self,
        destination: DestinationConversationRef,
    ) -> None:
        self._require_success(
            self._run(self._client.delete_channel(destination.id)),
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
            "Fluxer identity updates are not supported by the current adapter."
        )

    def delete_identity(
        self,
        destination: DestinationIdentityRef,
    ) -> None:
        raise CapabilityError(
            "Fluxer identity deletion is not supported by the current adapter."
        )

    def upload_attachment(
        self,
        attachment: CanonicalAttachment,
        data: bytes,
    ) -> DestinationAttachmentRef:
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
            "the current adapter."
        )

    def remove_attachment(
        self,
        message: DestinationMessageRef,
        attachment: CanonicalAttachment,
    ) -> None:
        raise CapabilityError(
            "Fluxer incremental attachment removal is not supported by "
            "the current adapter."
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
        attachment_payloads = [
            {"filename": attachment.filename, "data": data}
            for attachment, data in attachments
        ]

        result = self._run(
            self._client.send_message(
                channel_id=destination.id,
                content=message.content,
                attachments=attachment_payloads or None,
                author_name=self._author_name_for(message),
                reply_to_id=None,
            )
        )

        message_id = _required_id(result, "created Fluxer message")
        conversation_id = (
            _optional_id(result.get("channel_id"))
            if isinstance(result, dict)
            else None
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
        conversation_id = self._require_message_conversation(destination)
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
        conversation_id = self._require_message_conversation(destination)
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
            "Fluxer reply synchronization is not implemented by the current "
            "adapter."
        )

    def pin_message(
        self,
        message: DestinationMessageRef,
    ) -> None:
        conversation_id = self._require_message_conversation(message)
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
        conversation_id = self._require_message_conversation(message)
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

        conversation_id = self._require_message_conversation(message)
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

        conversation_id = self._require_message_conversation(message)
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
        mapping = self._identity_mappings.get(str(message.identity_key))
        return None if mapping is None else mapping.username

    @staticmethod
    def _fluxer_channel_type(
        conversation: CanonicalConversation,
    ) -> int:
        conversation_type = conversation.conversation_type
        value = getattr(conversation_type, "value", str(conversation_type))
        if value in {"channel", "group"}:
            return 0
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
                f"Fluxer message reference {message.id!r} is missing "
                "conversation_id."
            )
        return message.conversation_id

    @staticmethod
    def _require_success(result: bool, action: str) -> None:
        if not result:
            raise AdapterError(f"Fluxer failed to {action}.")

    @staticmethod
    def _run(awaitable: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)

        if hasattr(awaitable, "close"):
            awaitable.close()

        raise RuntimeError(
            "FluxerDestinationAdapter cannot execute from inside a running "
            "asyncio event loop. The synchronous DestinationAdapter boundary "
            "requires an async-to-sync boundary above the adapter."
        )


def _required_id(value: Any, description: str) -> str:
    if isinstance(value, dict):
        identifier = value.get("id")
    else:
        identifier = getattr(value, "id", None)

    if identifier is None:
        raise AdapterError(f"Fluxer returned no ID for {description}.")
    return str(identifier)


def _optional_id(value: Any) -> str | None:
    return None if value is None else str(value)
