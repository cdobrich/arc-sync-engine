"""Fluxer destination adapter.

This adapter translates canonical Archive-Sync Engine operations into calls to
an injected Fluxer client wrapper. It contains no synchronization or planning
logic. Unsupported destination features are rejected explicitly rather than
silently discarded.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from archive_sync_engine.adapters.capabilities import DestinationCapabilities
from archive_sync_engine.adapters.destination import DestinationAdapter
from archive_sync_engine.adapters.exceptions import AdapterError, AuthorizationError, CapabilityError
from archive_sync_engine.adapters.references import (
    DestinationAttachmentRef,
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)
from archive_sync_engine.operations import (
    AddReactionOperation,
    RemoveReactionOperation,
)
from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
    CanonicalReaction,
)


@dataclass(frozen=True, slots=True)
class FluxerCustomEmojiMapping:
    """Map a canonical/source custom emoji to an existing Fluxer emoji.

    Custom emoji IDs are platform-local, so the canonical source emoji ID must
    never be sent directly to Fluxer unless an explicit destination mapping
    establishes that correspondence.
    """

    source_emoji_id: str
    fluxer_emoji_id: str
    fluxer_emoji_name: str

    def __post_init__(self) -> None:
        if not self.source_emoji_id:
            raise ValueError("Fluxer custom emoji source ID must not be empty.")
        if not self.fluxer_emoji_id:
            raise ValueError("Fluxer custom emoji destination ID must not be empty.")
        if not self.fluxer_emoji_name:
            raise ValueError("Fluxer custom emoji destination name must not be empty.")


@dataclass(frozen=True, slots=True)
class FluxerIdentityMapping:
    """Destination mapping for one canonical identity.

    ``username`` is the canonical identity key used to select the mapping.
    ``fluxer_username`` is the destination display name to use when the
    destination API accepts an author name override. ``fluxer_auth_key`` is
    ``None`` for the adapter's default Fluxer bot account. A non-``None``
    value requests a masqueraded user account.
    """

    username: str
    fluxer_auth_key: str | None = None
    fluxer_username: str | None = None

    def __post_init__(self) -> None:
        if not self.username:
            raise ValueError("Fluxer identity mapping username must not be empty.")
        if self.fluxer_username == "":
            raise ValueError(
                "Fluxer identity mapping username must be None or a non-empty value."
            )
        if self.fluxer_auth_key == "":
            raise ValueError(
                "Fluxer identity mapping auth key must be None for the bot "
                "account or a non-empty value for a masqueraded user."
            )


class FluxerClientProtocol(Protocol):
    """Minimal async client surface required by the Fluxer adapter."""

    async def _create_fluxer_channel_from_discord(
        self,
        channel_data: dict[str, Any],
    ) -> Any:
        ...

    async def get_channel(
        self,
        channel_id: str,
    ) -> Any:
        ...

    async def update_channel(
        self,
        channel_id: str,
        *,
        name: str,
    ) -> Any:
        ...

    async def create_thread(
        self,
        parent_channel_id: str,
        *,
        name: str,
    ) -> Any:
        ...

    async def update_thread(
        self,
        thread_id: str,
        *,
        name: str,
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
        auth_key: str | None = None,
    ) -> bool:
        ...

    async def remove_reaction(
        self,
        channel_id: str,
        message_id: str,
        emoji_id_or_name: str,
        user_id: str = "@me",
        auth_key: str | None = None,
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

    async def remove_attachment(
        self,
        channel_id: str,
        message_id: str,
        filename: str,
    ) -> bool:
        ...

    async def get_guild_emojis(self) -> list[Any]:
        ...

    async def create_guild_emoji(
        self,
        *,
        name: str,
        image: bytes,
    ) -> Any:
        ...


class FluxerDestinationAdapter(DestinationAdapter):
    """Destination adapter for the currently supported Fluxer API surface."""

    _NAME = "fluxer"

    def __init__(
        self,
        client: FluxerClientProtocol,
        *,
        identity_mappings: tuple[FluxerIdentityMapping, ...] = (),
        custom_emoji_mappings: tuple[FluxerCustomEmojiMapping, ...] = (),
        identity_client_factory: Callable[[FluxerIdentityMapping], Any] | None = None,
        reaction_client_factory: Callable[[str], Any] | None = None,
        async_runner: Callable[[Any], Any] | None = None,
    ) -> None:
        self._client = client
        # The runtime supplies a persistent event-loop runner for real HTTP
        # clients.  Standalone adapters retain the synchronous fallback for
        # tests and callers that do not own a runtime.
        self._async_runner = async_runner

        self._legacy_reaction_client_factory = reaction_client_factory is not None and identity_client_factory is None

        if identity_client_factory is not None and reaction_client_factory is not None:
            raise ValueError(
                "Specify either identity_client_factory or reaction_client_factory, "
                "not both."
            )

        if identity_client_factory is None and reaction_client_factory is not None:
            identity_client_factory = (
                lambda mapping: reaction_client_factory(mapping.fluxer_auth_key)
                if mapping.fluxer_auth_key is not None
                else client
            )

        self._identity_client_factory = identity_client_factory

        mappings: dict[str, FluxerIdentityMapping] = {}
        for mapping in identity_mappings:
            if mapping.username in mappings:
                raise ValueError(
                    "Fluxer identity mappings must not contain duplicate "
                    f"canonical identity keys: {mapping.username!r}."
                )
            mappings[mapping.username] = mapping

        self._identity_mappings = mappings

        emoji_mappings: dict[str, FluxerCustomEmojiMapping] = {}
        for mapping in custom_emoji_mappings:
            if mapping.source_emoji_id in emoji_mappings:
                raise ValueError(
                    "Fluxer custom emoji mappings must not contain duplicate "
                    f"source emoji IDs: {mapping.source_emoji_id!r}."
                )
            emoji_mappings[mapping.source_emoji_id] = mapping
        self._custom_emoji_mappings = emoji_mappings
        self._custom_emoji_name_mappings: dict[str, tuple[FluxerCustomEmojiMapping, ...]] = {}
        self._rebuild_custom_emoji_name_mappings()
        self._archive_custom_emojis_prepared = False

    @property
    def name(self) -> str:
        return self._NAME

    def reconcile_synchronization_state(self, synchronization_state):
        """Invalidate destination references for Fluxer channels deleted externally."""
        state = synchronization_state
        for canonical_id, destination in tuple(state.conversations.items()):
            getter = getattr(self._client, "get_channel", None)
            if getter is None:
                http = getattr(self._client, "_http", None)
                getter = getattr(http, "get_channel", None) if http is not None else None
            if getter is None:
                return state
            try:
                self._run(getter(destination.id))
            except Exception as exc:
                if not _is_fluxer_not_found(exc):
                    raise
                state = state.without_messages_for_conversation(destination.id)
                state = state.without_conversation(canonical_id)
        return state

    def validate_operations(self, operations) -> None:
        """Validate configuration-dependent Fluxer operations before export.

        Fluxer reaction operations require an explicit mapping for the
        reaction actor. Static destination capabilities only indicate that
        reaction synchronization is possible when mappings exist; they cannot
        express whether every actor appearing in this particular plan is
        mapped. Validate the complete plan here so an unmapped reaction actor
        cannot cause a partial export after earlier operations have succeeded.
        """
        custom_reactions = []
        for operation in operations:
            if not isinstance(operation, (AddReactionOperation, RemoveReactionOperation)):
                continue

            identity_key = str(operation.reaction.identity_key)
            if identity_key not in self._identity_mappings:
                raise CapabilityError(
                    "Fluxer reaction synchronization requires an identity "
                    f"mapping for reaction actor {operation.reaction.identity_key}."
                )

            if operation.reaction.is_custom:
                custom_reactions.append(operation.reaction)

        if self._archive_custom_emojis_prepared:
            unresolved = [
                str(reaction.emoji_id)
                for reaction in custom_reactions
                if reaction.emoji_id is not None
                and str(reaction.emoji_id) not in self._custom_emoji_mappings
            ]
            if unresolved:
                raise CapabilityError(
                    "Fluxer custom emoji reaction synchronization requires a "
                    "destination emoji mapping for source emoji(s): "
                    + ", ".join(sorted(set(unresolved)))
                    + "."
                )

    def prepare_archive(self, archive, asset_store) -> None:
        """Provision every canonical custom emoji required by the archive."""
        try:
            destination_emojis = self._run(self._client.get_guild_emojis())
        except Exception as exc:
            raise AdapterError(
                "Unable to discover Fluxer guild emojis while preparing "
                "canonical custom emojis."
            ) from exc

        by_name: dict[str, list[Any]] = {}
        for emoji in destination_emojis or ():
            name = getattr(emoji, "name", None)
            emoji_id = getattr(emoji, "id", None)
            if isinstance(emoji, dict):
                name = emoji.get("name", name)
                emoji_id = emoji.get("id", emoji_id)
            if name is not None and emoji_id is not None:
                by_name.setdefault(str(name), []).append(emoji)

        for canonical in archive.iter_custom_emojis():
            source_id = str(canonical.id)
            if source_id in self._custom_emoji_mappings:
                continue

            candidates = by_name.get(canonical.name, [])
            if len(candidates) > 1:
                raise CapabilityError(
                    "Fluxer custom emoji synchronization cannot uniquely resolve "
                    f"archive emoji {source_id} ({canonical.name!r}); multiple "
                    "destination emojis have that name. Configure an explicit "
                    "emoji_mappings.discord entry."
                )

            if len(candidates) == 1:
                destination = candidates[0]
                destination_id = getattr(destination, "id", None)
                destination_name = getattr(destination, "name", None)
                if isinstance(destination, dict):
                    destination_id = destination.get("id", destination_id)
                    destination_name = destination.get("name", destination_name)
                self._custom_emoji_mappings[source_id] = FluxerCustomEmojiMapping(
                    source_emoji_id=source_id,
                    fluxer_emoji_id=str(destination_id),
                    fluxer_emoji_name=str(destination_name or canonical.name),
                )
                continue

            try:
                image = asset_store.get(canonical.sha256)
                created = self._run(
                    self._client.create_guild_emoji(
                        name=canonical.name,
                        image=image,
                    )
                )
            except Exception as exc:
                raise AdapterError(
                    "Unable to create Fluxer custom emoji "
                    f"{canonical.name!r} ({source_id})."
                ) from exc

            destination_id = getattr(created, "id", None)
            destination_name = getattr(created, "name", None)
            if isinstance(created, dict):
                destination_id = created.get("id", destination_id)
                destination_name = created.get("name", destination_name)
            if destination_id is None:
                raise AdapterError(
                    f"Fluxer did not return an ID when creating custom emoji {canonical.name!r}."
                )
            self._custom_emoji_mappings[source_id] = FluxerCustomEmojiMapping(
                source_emoji_id=source_id,
                fluxer_emoji_id=str(destination_id),
                fluxer_emoji_name=str(destination_name or canonical.name),
            )

        self._rebuild_custom_emoji_name_mappings()
        self._archive_custom_emojis_prepared = True

    @property
    def capabilities(self) -> DestinationCapabilities:
        return DestinationCapabilities(
            supports_threads=False,
            supports_message_editing=True,
            supports_conversation_updates=True,
            supports_message_deletion=True,
            supports_conversation_deletion=True,
            supports_message_pinning=True,
            # Canonical reactions are per-identity. Fluxer can only preserve
            # that identity when a masquerade mapping is configured.
            supports_reactions=bool(self._identity_mappings),
            # Re-adding an existing reaction is idempotent at the Fluxer
            # reaction endpoint, so replay can repair state established by a
            # prior run whose destination reaction was not retained.
            supports_idempotent_reaction_replay=bool(self._identity_mappings),
            # Fluxer natively supports custom emoji reactions.  Whether a
            # particular source emoji can be represented is validated against
            # explicit mappings or destination emoji discovery before any
            # export mutation occurs.
            supports_custom_emoji=True,
            supports_attachments=False,
            supports_attachment_removal=True,
            supports_initial_message_attachments=True,
            supports_initial_message_replying=True,
            supports_attachment_reordering=False,
            supports_replying=False,
            supports_identity_creation=False,
            supports_identity_mapping=bool(self._identity_mappings),
            supports_identity_updates=False,
            supports_identity_deletion=False,
        )

    def create_conversation(
        self,
        conversation: CanonicalConversation,
        parent: DestinationConversationRef | None = None,
    ) -> DestinationConversationRef:
        name = conversation.title or str(conversation.id)

        if conversation.parent_id is not None:
            raise CapabilityError(
                "Fluxer does not currently support creating thread "
                "conversations; thread export is intentionally skipped."
            )

        channel_type = self._fluxer_channel_type(conversation)
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
        name = conversation.title or str(conversation.id)
        if conversation.parent_id is None:
            update = getattr(self._client, "update_channel", None)
            if update is None:
                http = getattr(self._client, "_http", None)
                update = getattr(http, "modify_channel", None) if http is not None else None
            if update is None:
                raise CapabilityError("Fluxer channel updates are not available from the client.")
            self._require_success(
                self._run(update(destination.id, name=name)),
                f"update Fluxer conversation {destination.id}",
            )
            return

        self._require_success(
            self._run(
                self._client.update_thread(
                    destination.id,
                    name=name,
                )
            ),
            f"update Fluxer conversation {destination.id}",
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
        conversation_id = self._require_message_conversation(message)
        self._require_success(
            self._run(
                self._client.remove_attachment(
                    channel_id=conversation_id,
                    message_id=message.id,
                    filename=attachment.filename,
                )
            ),
            f"remove attachment {attachment.id} from Fluxer message {message.id}",
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
        reply_to: DestinationMessageRef | None = None,
    ) -> DestinationMessageRef:
        attachment_payloads = [
            {"filename": attachment.filename, "data": data}
            for attachment, data in attachments
        ]

        client = self._client_for_identity(message.identity_key)
        result = self._run(
            client.send_message(
                channel_id=destination.id,
                content=self._render_message_content(message.content),
                attachments=attachment_payloads or None,
                author_name=self._author_name_for(message),
                reply_to_id=(reply_to.id if reply_to is not None else None),
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
        client = self._client_for_identity(message.identity_key)
        try:
            self._require_success(
                self._run(
                    client.edit_message(
                        channel_id=conversation_id,
                        message_id=destination.id,
                        new_content=message.content,
                    )
                ),
                f"edit Fluxer message {destination.id}",
            )
        except Exception as exc:
            if _is_fluxer_forbidden(exc):
                raise AuthorizationError(
                    f"Fluxer message {destination.id} cannot be edited by the "
                    "authenticated identity."
                ) from exc
            raise

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
        self._require_supported_reaction(reaction)
        conversation_id = self._require_message_conversation(message)
        reaction_client = self._reaction_client(reaction)
        auth_key = self._auth_key_for_reaction(reaction)
        emoji = self._reaction_identifier(reaction)
        self._require_success(
            self._run(
                self._invoke_reaction_method(
                    reaction_client.apply_reaction,
                    channel_id=conversation_id,
                    message_id=message.id,
                    emoji=emoji,
                    auth_key=auth_key,
                    strip_auth_key=reaction_client is not self._client,
                )
            ),
            f"add reaction to Fluxer message {message.id}",
        )

    def remove_reaction(
        self,
        message: DestinationMessageRef,
        reaction: CanonicalReaction,
    ) -> None:
        self._require_supported_reaction(reaction)
        conversation_id = self._require_message_conversation(message)
        emoji = self._reaction_identifier(reaction)
        reaction_client = self._reaction_client(reaction)
        auth_key = self._auth_key_for_reaction(reaction)
        self._require_success(
            self._run(
                self._invoke_reaction_method(
                    reaction_client.remove_reaction,
                    channel_id=conversation_id,
                    message_id=message.id,
                    emoji_id_or_name=emoji,
                    user_id="@me",
                    auth_key=auth_key,
                    strip_auth_key=reaction_client is not self._client,
                )
            ),
            f"remove reaction from Fluxer message {message.id}",
        )

    def _client_for_identity(self, identity_key: Any) -> Any:
        mapping = self._identity_mappings.get(str(identity_key))
        if mapping is None or mapping.fluxer_auth_key is None:
            return self._client

        if self._identity_client_factory is None:
            return self._client

        try:
            client = self._identity_client_factory(mapping)
        except Exception as exc:
            if self._legacy_reaction_client_factory:
                raise AdapterError(
                    "actor client could not be created for reaction "
                    f"actor {identity_key}."
                ) from exc
            raise AdapterError(
                f"Failed to create Fluxer client for identity "
                f"{identity_key}."
            ) from exc

        if client is None:
            if self._legacy_reaction_client_factory:
                raise AdapterError(
                    "actor client factory returned no client for reaction "
                    f"actor {identity_key}."
                )
            raise AdapterError(
                f"Fluxer identity_client_factory returned no client for "
                f"identity {identity_key}."
            )
        return client

    def _reaction_client(self, reaction: CanonicalReaction) -> Any:
        mapping = self._identity_mappings.get(str(reaction.identity_key))
        if mapping is None:
            raise CapabilityError(
                "Fluxer reaction synchronization requires an identity "
                f"mapping for reaction actor {reaction.identity_key}."
            )
        if mapping.fluxer_auth_key is None:
            return self._client
        if self._identity_client_factory is not None:
            return self._client_for_identity(reaction.identity_key)
        return self._client

    def _require_supported_reaction(self, reaction: CanonicalReaction) -> None:
        if reaction.is_custom and reaction.emoji_id is None:
            raise CapabilityError(
                "Fluxer custom emoji reactions require a canonical emoji ID."
            )


    def _resolve_unmapped_custom_emojis(
        self,
        reactions: list[CanonicalReaction],
    ) -> None:
        """Resolve source custom emojis against explicit or destination mappings.

        The canonical reaction retains the stable source emoji ID and name, but
        destination emoji IDs are platform-local.  Explicit configuration always
        wins.  For mappings omitted from configuration, Fluxer emojis are looked
        up by exact name; a name must resolve uniquely.  The destination server
        must therefore already contain the emoji when no explicit mapping is
        supplied.  Creating a new emoji is intentionally not attempted here
        because the canonical reaction model does not contain the source emoji
        image bytes or animation metadata required to recreate it.
        """
        missing = {
            str(reaction.emoji_id): reaction
            for reaction in reactions
            if reaction.emoji_id is not None
            and str(reaction.emoji_id) not in self._custom_emoji_mappings
        }
        if not missing:
            return

        getter = getattr(self._client, "get_guild_emojis", None)
        if getter is None:
            raise CapabilityError(
                "Fluxer custom emoji reaction synchronization requires either "
                "an explicit emoji mapping or a destination client that can "
                "discover guild emojis."
            )

        try:
            destination_emojis = self._run(getter())
        except Exception as exc:
            raise AdapterError(
                "Unable to discover Fluxer guild emojis while resolving custom "
                "reaction mappings."
            ) from exc

        by_name: dict[str, list[Any]] = {}
        for emoji in destination_emojis or ():
            name = getattr(emoji, "name", None)
            emoji_id = getattr(emoji, "id", None)
            if name is None and isinstance(emoji, dict):
                name = emoji.get("name")
                emoji_id = emoji.get("id")
            if name is None or emoji_id is None:
                continue
            by_name.setdefault(str(name), []).append(emoji)

        unresolved: list[str] = []
        for source_id, reaction in missing.items():
            candidates = by_name.get(reaction.emoji, [])
            if len(candidates) != 1:
                unresolved.append(
                    f"{source_id} ({reaction.emoji!r})"
                )
                continue
            destination = candidates[0]
            destination_id = getattr(destination, "id", None)
            destination_name = getattr(destination, "name", None)
            if isinstance(destination, dict):
                destination_id = destination.get("id")
                destination_name = destination.get("name")
            assert destination_id is not None
            assert destination_name is not None
            self._custom_emoji_mappings[source_id] = FluxerCustomEmojiMapping(
                source_emoji_id=source_id,
                fluxer_emoji_id=str(destination_id),
                fluxer_emoji_name=str(destination_name),
            )

        self._rebuild_custom_emoji_name_mappings()

        if unresolved:
            raise CapabilityError(
                "Fluxer custom emoji reaction synchronization could not resolve "
                "destination emojis for: " + ", ".join(unresolved) + ". "
                "Configure an explicit emoji_mappings.discord entry or create "
                "the corresponding emoji on the Fluxer server."
            )

    def _reaction_identifier(self, reaction: CanonicalReaction) -> str:
        if not reaction.is_custom:
            return reaction.emoji
        if reaction.emoji_id is None:
            raise ValueError("Custom Fluxer reactions require emoji_id.")
        try:
            mapping = self._custom_emoji_mappings[str(reaction.emoji_id)]
        except KeyError as exc:
            raise CapabilityError(
                "Fluxer custom emoji reaction synchronization requires a "
                "destination emoji mapping for source emoji "
                f"{reaction.emoji_id}."
            ) from exc
        return f"{mapping.fluxer_emoji_name}:{mapping.fluxer_emoji_id}"

    def _rebuild_custom_emoji_name_mappings(self) -> None:
        by_name: dict[str, list[FluxerCustomEmojiMapping]] = {}
        for mapping in self._custom_emoji_mappings.values():
            by_name.setdefault(mapping.fluxer_emoji_name, []).append(mapping)
        self._custom_emoji_name_mappings = {
            name: tuple(values) for name, values in by_name.items()
        }

    def _render_message_content(self, content: str) -> str:
        """Translate Discord custom-emoji markup/shortcodes to Fluxer markup."""
        if not content or not self._custom_emoji_mappings:
            return content

        qualified = re.compile(r"<a?:([A-Za-z0-9_~+-]+):(\d+)>")

        def replace_qualified(match: re.Match[str]) -> str:
            source_id = match.group(2)
            mapping = self._custom_emoji_mappings.get(source_id)
            if mapping is None:
                return match.group(0)
            return f"<:{mapping.fluxer_emoji_name}:{mapping.fluxer_emoji_id}>"

        rendered = qualified.sub(replace_qualified, content)

        shortcode = re.compile(r"(?<!<):([A-Za-z0-9_~+-]+):")

        def replace_shortcode(match: re.Match[str]) -> str:
            name = match.group(1)
            candidates = self._custom_emoji_name_mappings.get(name, ())
            if len(candidates) != 1:
                return match.group(0)
            mapping = candidates[0]
            return f"<:{mapping.fluxer_emoji_name}:{mapping.fluxer_emoji_id}>"

        return shortcode.sub(replace_shortcode, rendered)

    def _author_name_for(
        self,
        message: CanonicalMessage,
    ) -> str | None:
        mapping = self._identity_mappings.get(str(message.identity_key))
        return None if mapping is None else (
            mapping.fluxer_username or mapping.username
        )

    def _auth_key_for_reaction(
        self,
        reaction: CanonicalReaction,
    ) -> str:
        """Return the configured Fluxer auth key for a reaction actor.

        Canonical reactions identify their actor explicitly. Applying an
        unmapped reaction as the adapter's default account would silently
        change canonical state, so reaction synchronization requires an
        explicit identity mapping.
        """
        mapping = self._identity_mappings.get(str(reaction.identity_key))
        if mapping is None:
            raise CapabilityError(
                "Fluxer reaction synchronization requires an identity "
                f"mapping for reaction actor {reaction.identity_key}."
            )
        return mapping.fluxer_auth_key

    @staticmethod
    def _invoke_reaction_method(
        method: Any,
        *,
        strip_auth_key: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Invoke a reaction client method with optional masquerade support.

        Older Fluxer clients accept the bot/default-account call shape only.
        Preserve that path when no auth key is requested. If a user mapping is
        configured, require the client to expose an ``auth_key`` parameter
        rather than silently applying the reaction as the bot.
        """
        auth_key = kwargs.get("auth_key")
        if strip_auth_key or auth_key is None:
            kwargs.pop("auth_key", None)
            return method(**kwargs)

        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError) as exc:
            raise AdapterError(
                "Fluxer reaction masquerading requires a client reaction "
                "method that accepts auth_key."
            ) from exc

        accepts_auth_key = "auth_key" in signature.parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if not accepts_auth_key:
            raise AdapterError(
                "Fluxer reaction masquerading is configured, but the client "
                "reaction method does not accept auth_key."
            )

        return method(**kwargs)

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

    def _run(self, awaitable: Any) -> Any:
        if self._async_runner is not None:
            return self._async_runner(awaitable)

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


def _is_fluxer_not_found(exc: BaseException) -> bool:
    """Return whether a Fluxer client exception represents HTTP 404."""
    return type(exc).__name__ == "NotFound" and "404" in str(exc)


def _is_fluxer_forbidden(exc: BaseException) -> bool:
    """Return whether a Fluxer client exception represents HTTP 403.

    Keep the optional fluxer.py dependency behind a duck-typed boundary so
    unit tests and installations without the package can still import the
    adapter module.
    """
    return type(exc).__name__ == "Forbidden" and "403" in str(exc)


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


