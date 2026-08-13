"""
Discord source adapter.

This module contains only Discord-to-canonical translation and source
platform access. Synchronization decisions remain in the engine.

The adapter accepts an already-created discord.py Client. This keeps
connection lifecycle outside the canonical import pipeline and makes the
adapter straightforward to test with a small fake client.

Vertical Slice 16 covers Discord identity and conversation discovery.
Vertical Slice 17 adds chronological message translation, including replies,
reactions, pins, and attachment metadata/bytes required by the canonical
message import contract.
Vertical Slice 19 adds active-thread discovery.
Vertical Slice 20 adds archived-thread discovery.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Awaitable, TypeVar

from archive_sync_engine.adapters.exceptions import (
    AdapterError,
    AuthorizationError,
    NotFoundError,
)
from archive_sync_engine.adapters.source import SourceAdapter
from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
    CanonicalReaction,
    ConversationType,
)
from archive_sync_engine.models.ids import (
    AttachmentId,
    ConversationId,
    EmojiId,
    IdentityKey,
    MessageId,
)


_T = TypeVar("_T")


class DiscordSourceAdapter(SourceAdapter):
    """
    Read canonical identities and conversations from Discord.

    ``guild_ids`` defines the source scope. IDs are intentionally retained
    only as opaque portions of canonical identifiers; the engine never
    interprets their structure.
    """

    def __init__(
        self,
        client: Any,
        guild_ids: Iterable[int | str],
    ) -> None:
        self._client = client
        self._guild_ids = tuple(
            sorted({int(guild_id) for guild_id in guild_ids})
        )
        self._conversation_channels: dict[str, Any] = {}
        self._message_cache: dict[str, tuple[Any, ...]] = {}
        self._attachment_bytes: dict[str, bytes] = {}

    @property
    def name(self) -> str:
        return "Discord"

    def iter_identities(self) -> Iterable[CanonicalIdentity]:
        """Yield every identity referenced by the configured Discord scope.

        Guild membership is not sufficient for historical archives: a user
        may have authored or reacted to an archived message without still
        appearing in ``guild.members``.  Discover message identities before
        the importer writes identities so the SourceAdapter contract remains
        complete without moving platform-specific logic into the importer.

        The historical message scan is cached as raw Discord messages.
        ``iter_messages()`` reuses that scan rather than making a second
        history request during the same adapter instance's import.
        """
        identities: dict[str, CanonicalIdentity] = {}

        for guild in self._iter_guilds():
            for member in self._guild_members(guild):
                identity = self._canonical_identity(member)
                identities.setdefault(str(identity.identity_key), identity)

        for conversation in self._discover_conversations():
            channel = self._conversation_channels[str(conversation.id)]
            if getattr(channel, "history", None) is None:
                continue
            messages = self._run(
                self._collect_raw_messages(channel),
            )
            self._message_cache[str(conversation.id)] = tuple(messages)

            for message in messages:
                author = getattr(message, "author", None)
                if author is not None:
                    identity = self._canonical_identity(author)
                    identities.setdefault(
                        str(identity.identity_key),
                        identity,
                    )

                for reaction_group in getattr(message, "reactions", ()):
                    users = getattr(reaction_group, "users", None)
                    if users is None:
                        raise AdapterError(
                            "Discord reaction does not expose reacting users."
                        )
                    async_identities = self._run(
                        self._collect_reaction_identities(users),
                    )
                    for identity in async_identities:
                        identities.setdefault(
                            str(identity.identity_key),
                            identity,
                        )

        yield from (identities[key] for key in sorted(identities))

    def iter_conversations(self) -> Iterable[CanonicalConversation]:
        """Yield message-bearing Discord channels and threads deterministically."""
        yield from self._discover_conversations()

    def _discover_conversations(self) -> list[CanonicalConversation]:
        conversations: dict[str, CanonicalConversation] = {}

        for guild in self._iter_guilds():
            channels = list(self._message_bearing_channels(guild))
            archived_threads = self._run(
                self._collect_archived_threads(guild),
            )
            channels.extend(archived_threads)
            channels.sort(key=self._channel_sort_key)

            for channel in channels:
                conversation = self._canonical_conversation(guild, channel)
                conversations.setdefault(str(conversation.id), conversation)
                self._conversation_channels.setdefault(
                    str(conversation.id),
                    channel,
                )

        return [conversations[key] for key in sorted(conversations)]

    def iter_messages(
        self,
        conversation: CanonicalConversation,
    ) -> Iterable[CanonicalMessage]:
        """Yield Discord messages in chronological order as canonical messages."""
        channel = self._conversation_channels.get(str(conversation.id))
        if channel is None:
            raise NotFoundError(
                f"Discord conversation {conversation.id} is not available."
            )

        cached_messages = self._message_cache.get(str(conversation.id))
        if cached_messages is not None:
            messages = self._run(
                self._canonicalize_cached_messages(
                    cached_messages,
                    channel,
                ),
            )
        else:
            messages = self._run(
                self._collect_messages(channel),
            )

        yield from messages

    def attachment_bytes(
        self,
        attachment: CanonicalAttachment,
    ) -> bytes:
        """Return bytes previously acquired while importing the message."""
        try:
            return self._attachment_bytes[attachment.sha256]
        except KeyError as exc:
            raise NotFoundError(
                f"Discord attachment {attachment.id} is not available."
            ) from exc

    @staticmethod
    async def _collect_raw_messages(
        channel: Any,
    ) -> list[Any]:
        history = channel.history(
            limit=None,
            oldest_first=True,
        )
        return [message async for message in history]

    async def _canonicalize_cached_messages(
        self,
        messages: tuple[Any, ...],
        channel: Any,
    ) -> list[CanonicalMessage]:
        pinned_ids = await self._collect_pinned_ids(channel)
        return [
            await self._canonical_message(
                message,
                pinned_ids=pinned_ids,
            )
            for message in messages
        ]

    async def _collect_messages(
        self,
        channel: Any,
    ) -> list[CanonicalMessage]:
        messages = await self._collect_raw_messages(channel)
        return await self._canonicalize_cached_messages(
            tuple(messages),
            channel,
        )

    @staticmethod
    async def _collect_reaction_identities(
        users: Any,
    ) -> list[CanonicalIdentity]:
        identities: list[CanonicalIdentity] = []
        async for user in users(limit=None):
            identities.append(
                DiscordSourceAdapter._canonical_identity(user),
            )
        return identities

    @staticmethod
    async def _collect_pinned_ids(channel: Any) -> set[str]:
        """Collect every pinned message exposed by the Discord channel.

        ``discord.py`` 2.6 changed ``pins()`` from returning a list to
        returning a paginated asynchronous iterator, and its default page
        limit is 50.  The archive must not silently truncate pinned-message
        state, so request the complete collection and support the current
        iterator contract.

        The awaitable branch is retained for the small adapter test doubles
        and older discord.py behavior; it does not change the canonical
        contract or introduce legacy synchronization state.
        """
        pins = getattr(channel, "pins", None)
        if pins is None:
            return set()

        result = pins(limit=None)
        pinned_ids: set[str] = set()

        if hasattr(result, "__aiter__"):
            async for message in result:
                message_id = getattr(message, "id", None)
                if message_id is not None:
                    pinned_ids.add(str(message_id))
            return pinned_ids

        pinned_messages = await result
        return {
            str(message.id)
            for message in pinned_messages
            if getattr(message, "id", None) is not None
        }

    async def _canonical_message(
        self,
        message: Any,
        *,
        pinned_ids: set[str],
    ) -> CanonicalMessage:
        message_id = getattr(message, "id", None)
        conversation_id = getattr(getattr(message, "channel", None), "id", None)
        author = getattr(message, "author", None)
        created_at = getattr(message, "created_at", None)

        if message_id is None or conversation_id is None:
            raise AdapterError(
                "Discord message is missing an ID or channel ID."
            )
        if author is None:
            raise AdapterError(
                f"Discord message {message_id} has no author."
            )
        if not isinstance(created_at, datetime):
            raise AdapterError(
                f"Discord message {message_id} has no valid creation timestamp."
            )

        attachments_list: list[CanonicalAttachment] = []
        for attachment in getattr(message, "attachments", ()):
            attachments_list.append(
                await self._canonical_attachment(attachment)
            )
        attachments = tuple(attachments_list)
        reactions_list: list[CanonicalReaction] = []
        for reaction_group in getattr(message, "reactions", ()):
            reactions_list.extend(
                await self._canonical_reactions(
                    reaction_group,
                )
            )
        reactions = tuple(reactions_list)

        reference = getattr(message, "reference", None)
        reply_message_id = getattr(reference, "message_id", None)

        return CanonicalMessage(
            id=MessageId(
                self._message_key(message_id),
            ),
            conversation_id=ConversationId(
                self._conversation_key_from_channel_id(
                    conversation_id,
                ),
            ),
            identity_key=self._canonical_identity(author).identity_key,
            content=str(getattr(message, "content", "") or ""),
            created_at=created_at,
            edited_at=getattr(message, "edited_at", None),
            reply_to=(
                MessageId(self._message_key(reply_message_id))
                if reply_message_id is not None
                else None
            ),
            pinned=str(message_id) in pinned_ids,
            attachments=attachments,
            reactions=reactions,
        )

    async def _canonical_attachment(
        self,
        attachment: Any,
    ) -> CanonicalAttachment:
        attachment_id = getattr(attachment, "id", None)
        filename = getattr(attachment, "filename", None)
        if attachment_id is None or filename is None:
            raise AdapterError(
                "Discord attachment is missing an ID or filename."
            )

        reader = getattr(attachment, "read", None)
        if reader is None:
            raise AdapterError(
                f"Discord attachment {attachment_id} cannot be downloaded."
            )

        data = await reader()
        digest = hashlib.sha256(data).hexdigest()
        self._attachment_bytes[digest] = bytes(data)

        return CanonicalAttachment(
            id=AttachmentId(str(attachment_id)),
            filename=str(filename),
            content_type=(
                str(getattr(attachment, "content_type"))
                if getattr(attachment, "content_type", None) is not None
                else None
            ),
            size=len(data),
            sha256=digest,
        )

    async def _canonical_reactions(
        self,
        reaction: Any,
    ) -> tuple[CanonicalReaction, ...]:
        emoji = getattr(reaction, "emoji", None)
        if emoji is None:
            raise AdapterError("Discord reaction is missing its emoji.")

        emoji_id = getattr(emoji, "id", None)
        is_custom = emoji_id is not None
        emoji_name = getattr(emoji, "name", None)
        emoji_text = str(emoji_name if emoji_name is not None else emoji)

        users = getattr(reaction, "users", None)
        if users is None:
            raise AdapterError(
                "Discord reaction does not expose reacting users."
            )

        result: list[CanonicalReaction] = []
        async for user in users(limit=None):
            identity = self._canonical_identity(user)
            result.append(
                CanonicalReaction(
                    identity_key=identity.identity_key,
                    emoji=emoji_text,
                    emoji_id=(
                        EmojiId(str(emoji_id))
                        if is_custom
                        else None
                    ),
                    is_custom=is_custom,
                )
            )

        return tuple(result)

    def _iter_guilds(self) -> Iterable[Any]:
        for guild_id in self._guild_ids:
            guild = self._client.get_guild(guild_id)
            if guild is None:
                guild = self._run(
                    self._client.fetch_guild(guild_id)
                )

            if guild is None:
                raise NotFoundError(
                    f"Discord guild {guild_id} was not found."
                )

            yield guild

    @staticmethod
    def _guild_members(guild: Any) -> Iterable[Any]:
        """Return cached members without making identity discovery destination-specific."""
        members = getattr(guild, "members", None)
        if members is None:
            raise AuthorizationError(
                "Discord guild member data is unavailable."
            )
        return members

    @staticmethod
    def _canonical_identity(member: Any) -> CanonicalIdentity:
        user = getattr(member, "_user", member)
        user_id = getattr(user, "id", None)
        if user_id is None:
            raise AdapterError("Discord member has no user ID.")

        display_name = (
            getattr(member, "display_name", None)
            or getattr(user, "global_name", None)
            or getattr(user, "name", None)
            or str(user_id)
        )

        avatar = getattr(member, "display_avatar", None)
        avatar_url = (
            str(getattr(avatar, "url", avatar))
            if avatar is not None
            else None
        )

        return CanonicalIdentity(
            identity_key=IdentityKey(
                f"discord:user:{user_id}"
            ),
            display_name=str(display_name),
            avatar_url=avatar_url,
            is_bot=bool(getattr(user, "bot", False)),
        )

    @staticmethod
    def _message_bearing_channels(guild: Any) -> Iterable[Any]:
        """Return message-bearing channels and discovered active threads.

        Discord exposes active threads separately from the guild channel
        collection in some client/library versions.  Treat both collections
        as source input and deduplicate by Discord channel ID so the canonical
        archive sees each conversation exactly once.
        """

        channels = getattr(guild, "channels", ())
        threads = getattr(guild, "threads", ())

        candidates = (
            *channels,
            *threads,
        )

        seen_ids: set[str] = set()

        for channel in candidates:
            if not DiscordSourceAdapter._is_message_bearing_channel(
                channel,
            ):
                continue

            channel_id = getattr(channel, "id", None)
            if channel_id is None:
                continue

            key = str(channel_id)
            if key in seen_ids:
                continue

            seen_ids.add(key)
            yield channel

    @staticmethod
    async def _collect_archived_threads(
        guild: Any,
    ) -> list[Any]:
        """Collect public and private archived threads from message channels.

        ``discord.py`` exposes archived threads through the parent channel's
        ``archived_threads`` async iterator rather than ``Guild.threads``.
        Passing ``limit=None`` requests the complete available archive.
        Private archived threads require the permissions enforced by
        ``discord.py``; permission failures therefore propagate instead of
        silently producing an incomplete canonical archive.
        """
        archived: dict[str, Any] = {}

        for channel in getattr(guild, "channels", ()):
            if DiscordSourceAdapter._is_thread(channel):
                continue

            archived_threads = getattr(channel, "archived_threads", None)
            if archived_threads is None:
                continue

            for private in (False, True):
                iterator = archived_threads(
                    private=private,
                    joined=False,
                    limit=None,
                )
                async for thread in iterator:
                    thread_id = getattr(thread, "id", None)
                    if thread_id is None:
                        raise AdapterError(
                            "Discord archived thread has no ID."
                        )
                    archived.setdefault(str(thread_id), thread)

        return sorted(
            archived.values(),
            key=DiscordSourceAdapter._channel_sort_key,
        )

    @staticmethod
    def _is_message_bearing_channel(channel: Any) -> bool:
        class_name = type(channel).__name__.lower()
        if class_name in {
            "textchannel",
            "newschannel",
            "forumchannel",
            "thread",
            "threadchannel",
        }:
            return True

        channel_type = getattr(channel, "type", None)
        type_name = getattr(channel_type, "name", "")
        return str(type_name).lower() in {
            "text",
            "news",
            "forum",
            "public_thread",
            "private_thread",
            "news_thread",
        }

    @staticmethod
    def _canonical_conversation(
        guild: Any,
        channel: Any,
    ) -> CanonicalConversation:
        channel_id = getattr(channel, "id", None)
        if channel_id is None:
            raise AdapterError("Discord channel has no ID.")

        is_thread = DiscordSourceAdapter._is_thread(channel)
        parent_id = getattr(channel, "parent_id", None)
        if parent_id is None:
            parent = getattr(channel, "parent", None)
            parent_id = getattr(parent, "id", None)

        conversation_type = (
            ConversationType.THREAD
            if is_thread
            else ConversationType.CHANNEL
        )

        canonical_parent_id = (
            ConversationId(
                DiscordSourceAdapter._conversation_key(
                    guild,
                    parent_id,
                )
            )
            if is_thread and parent_id is not None
            else None
        )

        created_at = getattr(channel, "created_at", None)
        if created_at is not None and not isinstance(created_at, datetime):
            created_at = None

        return CanonicalConversation(
            id=ConversationId(
                DiscordSourceAdapter._conversation_key(
                    guild,
                    channel_id,
                )
            ),
            conversation_type=conversation_type,
            title=getattr(channel, "name", None),
            parent_id=canonical_parent_id,
            created_at=created_at,
        )

    def _conversation_key_from_channel_id(self, channel_id: Any) -> str:
        for conversation_id, channel in self._conversation_channels.items():
            if str(getattr(channel, "id", "")) == str(channel_id):
                return conversation_id
        raise NotFoundError(
            f"Discord channel {channel_id} is not available."
        )

    @staticmethod
    def _message_key(message_id: Any) -> str:
        return f"discord:message:{message_id}"

    @staticmethod
    def _conversation_key(guild: Any, channel_id: Any) -> str:
        guild_id = getattr(guild, "id", None)
        if guild_id is None or channel_id is None:
            raise AdapterError(
                "Discord conversation requires guild and channel IDs."
            )
        return f"discord:guild:{guild_id}:channel:{channel_id}"

    @staticmethod
    def _is_thread(channel: Any) -> bool:
        class_name = type(channel).__name__.lower()
        if "thread" in class_name:
            return True

        channel_type = getattr(channel, "type", None)
        type_name = str(getattr(channel_type, "name", "")).lower()
        return type_name in {
            "public_thread",
            "private_thread",
            "news_thread",
        }

    @staticmethod
    def _channel_sort_key(channel: Any) -> tuple[int, int, str]:
        return (
            int(getattr(channel, "position", 0)),
            int(getattr(channel, "id", 0)),
            str(getattr(channel, "name", "")),
        )

    @staticmethod
    def _run(awaitable: Awaitable[_T]) -> _T:
        """Execute one Discord coroutine for the synchronous SourceAdapter contract."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)

        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        raise AdapterError(
            "DiscordSourceAdapter synchronous methods cannot run inside an active event loop."
        )
