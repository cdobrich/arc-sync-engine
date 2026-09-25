"""Fluxer source adapter.

This module translates Fluxer REST source data into the canonical Archive
models.  It deliberately has no synchronization or destination logic.
"""
from __future__ import annotations

import hashlib
import logging
from urllib.error import HTTPError
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Callable

from .exceptions import AdapterError, NotFoundError
from .source import SourceAdapter
from ..models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalCustomEmoji,
    CanonicalIdentity,
    CanonicalMessage,
    CanonicalReaction,
    ConversationType,
)
from ..models.ids import AttachmentId, ConversationId, EmojiId, IdentityKey, MessageId


class FluxerSourceClientProtocol:
    """Small async client surface required by :class:`FluxerSourceAdapter`."""

    async def get_guild_channels(self, guild_id: str) -> list[Any]: ...
    async def get_channel_messages(self, channel_id: str, *, before: str | None = None) -> list[Any]: ...
    async def get_pinned_message_ids(self, channel_id: str) -> set[str]: ...
    async def get_reaction_users(self, channel_id: str, message_id: str, emoji: str) -> list[Any]: ...
    async def get_guild_emojis(self, guild_id: str) -> list[Any]: ...
    async def download_url(self, url: str) -> bytes: ...


logger = logging.getLogger(__name__)


class FluxerSourceAdapter(SourceAdapter):
    """Read one or more Fluxer guilds into canonical Archive models."""

    def __init__(
        self,
        client: FluxerSourceClientProtocol,
        guild_ids: Iterable[str],
        *,
        runner: Callable[[Any], Any] | None = None,
    ) -> None:
        self._client = client
        self._guild_ids = tuple(sorted({str(value) for value in guild_ids}))
        if not self._guild_ids:
            raise ValueError("Fluxer source adapter requires at least one guild ID.")
        self._runner = runner
        self._channels: dict[str, dict[str, Any]] = {}
        self._messages: dict[str, tuple[dict[str, Any], ...]] = {}
        self._attachment_bytes: dict[str, bytes] = {}
        self._custom_emoji_bytes: dict[str, bytes] = {}
        self._reaction_users: dict[tuple[str, str, str], tuple[dict[str, Any], ...]] = {}
        self._identities: dict[str, CanonicalIdentity] = {}

    @property
    def name(self) -> str:
        return "Fluxer"

    def set_runner(self, runner: Callable[[Any], Any] | None) -> None:
        self._runner = runner

    def iter_conversations(self) -> Iterable[CanonicalConversation]:
        conversations: list[CanonicalConversation] = []
        for guild_id in self._guild_ids:
            channels = self._run(self._client.get_guild_channels(guild_id))
            for channel in channels or ():
                channel_id = self._field(channel, "id")
                if channel_id is None:
                    raise AdapterError("Fluxer channel is missing an ID.")
                channel_id = str(channel_id)
                channel_type = int(self._field(channel, "type", 0) or 0)
                # Archive only message-bearing guild channels.  Categories and
                # voice/link channels do not have message history.
                if channel_type not in {0, 5, 15}:
                    continue
                self._channels[channel_id] = dict(channel) if isinstance(channel, dict) else channel
                conversations.append(self._canonical_conversation(guild_id, channel))

        conversations.sort(key=lambda item: str(item.id))
        return conversations

    def iter_identities(self) -> Iterable[CanonicalIdentity]:
        # Fluxer reaction payloads contain counts, not all reacting users.
        # Walk the complete message set and explicitly resolve reaction users
        # so the canonical archive retains one reaction event per identity.
        for conversation in self.iter_conversations():
            for message in self._raw_messages_for_conversation(conversation):
                author = self._field(message, "author", {}) or {}
                identity = self._canonical_identity(author)
                self._identities[str(identity.identity_key)] = identity
                self._load_reaction_identities(conversation, message)

        return [self._identities[key] for key in sorted(self._identities)]

    def iter_custom_emojis(self) -> Iterable[CanonicalCustomEmoji]:
        emojis: dict[str, Any] = {}
        for guild_id in self._guild_ids:
            for emoji in self._run(self._client.get_guild_emojis(guild_id)) or ():
                emoji_id = self._field(emoji, "id")
                if emoji_id is not None:
                    emojis[str(emoji_id)] = emoji

        result: list[CanonicalCustomEmoji] = []
        for emoji_id in sorted(emojis):
            emoji = emojis[emoji_id]
            name = str(self._field(emoji, "name") or "")
            if not name:
                continue
            try:
                data = self._read_emoji_bytes(emoji, emoji_id)
            except AdapterError as exc:
                # A Fluxer emoji can remain present in the metadata endpoint
                # after its backing asset is unavailable.  The canonical
                # Archive requires real bytes for a custom-emoji asset, so do
                # not manufacture a bogus digest/placeholder asset and do not
                # abort the entire source import.  The message/reaction data
                # remains importable and the missing asset is explicitly
                # diagnosed.
                logger.warning(
                    "Skipping Fluxer custom emoji %s (%s): %s",
                    emoji_id,
                    name,
                    exc,
                )
                continue
            digest = hashlib.sha256(data).hexdigest()
            self._custom_emoji_bytes[emoji_id] = data
            animated = bool(self._field(emoji, "animated", False))
            result.append(
                CanonicalCustomEmoji(
                    id=EmojiId(emoji_id),
                    name=name,
                    animated=animated,
                    content_type="image/gif" if animated else "image/png",
                    size=len(data),
                    sha256=digest,
                )
            )
        return result

    def _read_emoji_bytes(self, emoji: Any, emoji_id: str) -> bytes:
        """Read custom-emoji bytes from the source client or asset URL.

        Fluxer-py models expose emoji metadata but not a readable asset
        method.  The source runtime therefore may normalize an emoji into a
        mapping containing a concrete asset URL.  Accept both forms here so
        the canonical adapter does not depend on a particular Fluxer-py
        model representation.
        """
        direct = self._field(emoji, "bytes")
        if direct is None:
            direct = self._field(emoji, "content")
        if direct is not None:
            data = bytes(direct)
            if data:
                return data

        reader = self._field(emoji, "read")
        if callable(reader):
            data = self._run(reader())
            data = bytes(data)
            if data:
                return data

        url = (
            self._field(emoji, "url")
            or self._field(emoji, "proxy_url")
            or self._field(emoji, "image_url")
        )
        if url:
            candidate_urls = [str(url)]
            base_url = str(url).rsplit("/", 1)[0]
            filename = str(url).rsplit("/", 1)[-1]
            if "." in filename:
                stem = filename.rsplit(".", 1)[0]
                candidate_urls.extend(
                    f"{base_url}/{stem}{extension}"
                    for extension in ("", ".png", ".gif", ".webp", ".svg")
                    if f"{base_url}/{stem}{extension}" not in candidate_urls
                )
            else:
                candidate_urls.extend(
                    f"{str(url)}{extension}"
                    for extension in (".png", ".gif", ".webp", ".svg")
                )
            for candidate_url in candidate_urls:
                try:
                    data = self._run(self._client.download_url(candidate_url))
                except HTTPError as exc:
                    if exc.code == 404:
                        continue
                    raise
                data = bytes(data)
                if data:
                    return data

        raise AdapterError(
            f"Fluxer custom emoji {emoji_id} does not expose readable asset bytes."
        )

    def custom_emoji_bytes(self, emoji: CanonicalCustomEmoji) -> bytes:
        try:
            return self._custom_emoji_bytes[str(emoji.id)]
        except KeyError as exc:
            raise NotFoundError(f"Fluxer custom emoji {emoji.id} is not available.") from exc

    def iter_pinned_message_ids(
        self,
        conversation: CanonicalConversation,
    ) -> Iterable[str] | None:
        """Return the complete current Fluxer pin set for one channel."""
        getter = getattr(self._client, "get_pinned_message_ids", None)
        if getter is None:
            return None
        channel_id = self._source_channel_id(conversation)
        pinned_ids = self._run(getter(channel_id))
        return tuple(
            f"fluxer:message:{message_id}"
            for message_id in sorted(str(value) for value in pinned_ids)
        )

    def iter_messages(self, conversation: CanonicalConversation) -> Iterable[CanonicalMessage]:
        raw_messages = self._raw_messages_for_conversation(conversation)
        pinned_ids = {
            str(message.get("id"))
            for message in raw_messages
            if bool(message.get("pinned")) and message.get("id") is not None
        }
        pin_getter = getattr(self._client, "get_pinned_message_ids", None)
        if pin_getter is not None:
            pinned_ids.update(
                str(message_id)
                for message_id in self._run(
                    pin_getter(self._source_channel_id(conversation))
                )
            )
        messages = [
            self._canonical_message(conversation, message, pinned_ids=pinned_ids)
            for message in raw_messages
        ]
        messages.sort(key=lambda item: (item.created_at, str(item.id)))
        return messages

    def attachment_bytes(self, attachment: CanonicalAttachment) -> bytes:
        try:
            return self._attachment_bytes[attachment.sha256]
        except KeyError as exc:
            raise NotFoundError(f"Fluxer attachment {attachment.id} is not available.") from exc

    def _raw_messages_for_conversation(self, conversation: CanonicalConversation) -> tuple[dict[str, Any], ...]:
        channel_id = self._source_channel_id(conversation)
        cached = self._messages.get(channel_id)
        if cached is not None:
            return cached

        collected: list[dict[str, Any]] = []
        before: str | None = None
        seen: set[str] = set()
        while True:
            page = self._run(self._client.get_channel_messages(channel_id, before=before)) or []
            if not page:
                break
            for message in page:
                message_id = self._field(message, "id")
                if message_id is None or str(message_id) in seen:
                    continue
                seen.add(str(message_id))
                collected.append(dict(message) if isinstance(message, dict) else message)
            oldest = self._message_sort_key(page[-1])
            if oldest is None or len(page) == 0:
                break
            if before == str(oldest):
                break
            before = str(oldest)
            if len(page) < 100:
                break

        collected.sort(key=lambda message: self._message_sort_key(message) or "")
        result = tuple(collected)
        self._messages[channel_id] = result
        return result

    def _load_reaction_identities(
        self,
        conversation: CanonicalConversation,
        message: dict[str, Any],
    ) -> None:
        channel_id = self._source_channel_id(conversation)
        message_id = str(self._field(message, "id"))
        for reaction in self._field(message, "reactions", ()) or ():
            emoji = self._field(reaction, "emoji", {}) or {}
            emoji_id = self._field(emoji, "id")
            emoji_name = str(self._field(emoji, "name") or "")
            emoji_key = str(emoji_id if emoji_id is not None else emoji_name)
            cache_key = (channel_id, message_id, emoji_key)
            users = self._reaction_users.get(cache_key)
            if users is None:
                users = tuple(
                    dict(user) if isinstance(user, dict) else user
                    for user in (self._run(
                        self._client.get_reaction_users(channel_id, message_id, emoji_key)
                    ) or ())
                )
                self._reaction_users[cache_key] = users
            for user in users:
                identity = self._canonical_identity(user)
                self._identities[str(identity.identity_key)] = identity

    def _canonical_message(
        self,
        conversation: CanonicalConversation,
        message: dict[str, Any],
        *,
        pinned_ids: set[str],
    ) -> CanonicalMessage:
        message_id = self._field(message, "id")
        if message_id is None:
            raise AdapterError("Fluxer message is missing an ID.")
        author = self._field(message, "author", {}) or {}
        identity = self._canonical_identity(author)
        created_at = self._parse_datetime(self._field(message, "timestamp"))
        if created_at is None:
            raise AdapterError(f"Fluxer message {message_id} has no valid timestamp.")

        attachments: list[CanonicalAttachment] = []
        for raw_attachment in self._field(message, "attachments", ()) or ():
            attachment_id = self._field(raw_attachment, "id")
            filename = self._field(raw_attachment, "filename")
            url = self._field(raw_attachment, "url") or self._field(raw_attachment, "proxy_url")
            if attachment_id is None or filename is None or not url:
                raise AdapterError(f"Fluxer message {message_id} has an invalid attachment.")
            data = self._run(self._client.download_url(str(url)))
            data = bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            self._attachment_bytes[digest] = data
            attachments.append(
                CanonicalAttachment(
                    id=AttachmentId(str(attachment_id)),
                    filename=str(filename),
                    content_type=(
                        str(self._field(raw_attachment, "content_type"))
                        if self._field(raw_attachment, "content_type") is not None
                        else None
                    ),
                    size=len(data),
                    sha256=digest,
                )
            )

        reactions: list[CanonicalReaction] = []
        channel_id = self._source_channel_id(conversation)
        for reaction in self._field(message, "reactions", ()) or ():
            emoji = self._field(reaction, "emoji", {}) or {}
            emoji_id = self._field(emoji, "id")
            emoji_name = str(self._field(emoji, "name") or "")
            emoji_key = str(emoji_id if emoji_id is not None else emoji_name)
            users = self._reaction_users.get((channel_id, str(message_id), emoji_key))
            if users is None:
                users = tuple(
                    dict(user) if isinstance(user, dict) else user
                    for user in (self._run(
                        self._client.get_reaction_users(channel_id, str(message_id), emoji_key)
                    ) or ())
                )
                self._reaction_users[(channel_id, str(message_id), emoji_key)] = users
            for user in users:
                reaction_identity = self._canonical_identity(user)
                reactions.append(
                    CanonicalReaction(
                        identity_key=reaction_identity.identity_key,
                        emoji=emoji_name,
                        emoji_id=EmojiId(str(emoji_id)) if emoji_id is not None else None,
                        is_custom=emoji_id is not None,
                    )
                )

        content = str(self._field(message, "content") or "")
        if not content and not attachments:
            content = self._system_message_content(message, identity.display_name)

        reference = self._field(message, "message_reference") or {}
        reply_id = self._field(reference, "message_id")

        return CanonicalMessage(
            id=MessageId(f"fluxer:message:{message_id}"),
            conversation_id=conversation.id,
            identity_key=identity.identity_key,
            content=content,
            created_at=created_at,
            edited_at=self._parse_datetime(self._field(message, "edited_timestamp")),
            reply_to=MessageId(f"fluxer:message:{reply_id}") if reply_id is not None else None,
            pinned=str(message_id) in pinned_ids,
            attachments=tuple(attachments),
            reactions=tuple(reactions),
        )

    @staticmethod
    def _system_message_content(message: dict[str, Any], author_name: str) -> str:
        message_type = int(FluxerSourceAdapter._field(message, "type", 0) or 0)
        return {
            1: f"{author_name} added a user to this channel.",
            2: f"{author_name} removed a user from this channel.",
            3: "A call occurred in this channel.",
            4: f"{author_name} changed the channel name.",
            5: f"{author_name} changed the channel icon.",
            6: f"{author_name} pinned a message to this channel.",
            7: f"{author_name} joined this channel.",
        }.get(message_type, f"[Fluxer system message type {message_type}]")

    def _canonical_conversation(self, guild_id: str, channel: Any) -> CanonicalConversation:
        channel_id = str(self._field(channel, "id"))
        channel_type = int(self._field(channel, "type", 0) or 0)
        parent_id = self._field(channel, "parent_id")
        is_thread = channel_type in {15, 16, 17}
        return CanonicalConversation(
            id=ConversationId(f"fluxer:guild:{guild_id}:channel:{channel_id}"),
            conversation_type=ConversationType.THREAD if is_thread else ConversationType.CHANNEL,
            title=self._field(channel, "name"),
            parent_id=(ConversationId(f"fluxer:guild:{guild_id}:channel:{parent_id}") if is_thread and parent_id else None),
            created_at=self._parse_datetime(self._field(channel, "created_at")),
        )

    def _source_channel_id(self, conversation: CanonicalConversation) -> str:
        prefix = "fluxer:guild:"
        marker = ":channel:"
        value = str(conversation.id)
        if not value.startswith(prefix) or marker not in value:
            raise NotFoundError(f"Fluxer conversation {conversation.id} is not available.")
        return value.rsplit(marker, 1)[1]

    @staticmethod
    def _canonical_identity(user: Any) -> CanonicalIdentity:
        user_id = FluxerSourceAdapter._field(user, "id")
        if user_id is None:
            raise AdapterError("Fluxer user is missing an ID.")
        username = str(FluxerSourceAdapter._field(user, "global_name") or FluxerSourceAdapter._field(user, "username") or user_id)
        avatar = FluxerSourceAdapter._field(user, "avatar_url") or FluxerSourceAdapter._field(user, "avatar")
        return CanonicalIdentity(
            identity_key=IdentityKey(f"fluxer:user:{user_id}"),
            display_name=username,
            avatar_url=str(avatar) if avatar else None,
            is_bot=bool(FluxerSourceAdapter._field(user, "bot", False)),
            metadata={"username": str(FluxerSourceAdapter._field(user, "username") or username)},
        )

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo is not None and value.utcoffset() is not None else value.replace(tzinfo=timezone.utc)
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _message_sort_key(message: Any) -> str | None:
        timestamp = FluxerSourceAdapter._field(message, "timestamp")
        return str(timestamp) if timestamp is not None else None

    @staticmethod
    def _field(value: Any, name: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    def _run(self, awaitable: Any) -> Any:
        if self._runner is not None:
            return self._runner(awaitable)
        import asyncio
        return asyncio.run(awaitable)
