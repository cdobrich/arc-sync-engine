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
Vertical Slice 24 makes unresolved Discord reply references explicit: the
canonical reply target is preserved by message ID even when Discord does not
provide the referenced message object.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, TypeVar

from archive_sync_engine.adapters.exceptions import (
    AdapterError,
    AuthorizationError,
    NotFoundError,
)
from archive_sync_engine.adapters.source import IdentityDiscoveryBatch, SourceAdapter, SourceRefreshCursor
from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalCustomEmoji,
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

    _INCREMENTAL_LOOKBACK = timedelta(days=7)

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
        self._incremental_message_cache: dict[str, tuple[Any, ...]] = {}
        self._current_message_id: str | None = None
        self._current_message_identities: tuple[CanonicalIdentity, ...] = ()
        self._attachment_bytes: dict[str, bytes] = {}
        self._attachment_cache_bytes = 0
        self._attachment_cache_limit = 64 * 1024 * 1024
        self._custom_emoji_bytes: dict[str, bytes] = {}
        self._custom_emoji_objects: dict[str, Any] = {}
        self._runner: Callable[[Awaitable[Any]], Any] | None = None
        self._identity_scan_progress_callback: Callable[[int, str], None] | None = None
        self._identity_scan_messages_scanned = 0
        self._history_retry_attempts = 5
        self._history_retry_base_delay = 2.0
        self._history_retry_max_delay = 60.0
        self._incremental_lookback = self._INCREMENTAL_LOOKBACK
        self._attachment_retry_attempts = 5
        self._attachment_retry_base_delay = 2.0
        self._attachment_retry_max_delay = 60.0

    @property
    def name(self) -> str:
        return "Discord"

    @property
    def incremental_refresh_lookback(self) -> timedelta:
        """Re-read a bounded recent window so mutable Discord state is seen.

        Discord does not expose a general "messages changed since" endpoint.
        The configured overlap catches ordinary edits, pins, reactions, and
        attachment changes without re-reading the entire channel history.
        Seven days is the default; older mutations remain a source limitation.
        """
        return self._incremental_lookback

    def set_incremental_refresh_lookback_days(self, days: int | float) -> None:
        """Configure the overlap used for completed-import incremental refreshes.

        Seven days remains the default. Zero is permitted for callers who
        explicitly want no overlap; negative and non-finite values are rejected.
        """
        import math

        value = float(days)
        if not math.isfinite(value) or value < 0:
            raise ValueError("Incremental refresh lookback days must be a finite non-negative number.")
        self._incremental_lookback = timedelta(days=value)

    def set_identity_scan_progress_callback(
        self,
        callback: Callable[[int, str], None] | None,
    ) -> None:
        """Set an optional callback for long-running full identity discovery.

        ``current`` is the number of historical messages scanned. A zero value
        marks a phase or channel boundary; ``detail`` explains the current
        operation. This deliberately avoids importing CLI/progress types into
        the adapter layer.
        """
        self._identity_scan_progress_callback = callback

    def _report_identity_scan_progress(self, current: int, detail: str) -> None:
        callback = self._identity_scan_progress_callback
        if callback is not None:
            callback(current, detail)

    def iter_identities(self) -> Iterable[CanonicalIdentity]:
        """Yield every identity referenced by the configured Discord scope.

        Guild membership is not sufficient for historical archives: a user
        may have authored or reacted to an archived message without still
        appearing in ``guild.members``.  Discover message identities before
        the importer writes identities so the SourceAdapter contract remains
        complete without moving platform-specific logic into the importer.

        The historical message scan is cached as raw Discord messages.
        ``iter_messages()`` reuses that complete scan rather than making a
        second history request during the same adapter instance's import.
        Incremental refresh windows use a separate cache so they can never
        masquerade as a complete source traversal.
        """
        identities: dict[str, CanonicalIdentity] = {}
        self._identity_scan_messages_scanned = 0
        self._report_identity_scan_progress(0, "Loading Discord guild members...")

        for guild in self._iter_guilds():
            self._report_identity_scan_progress(
                0,
                f"Loading members for guild {(getattr(guild, 'name', None) or getattr(guild, 'id', 'unknown'))}...",
            )
            members = self._run(
                self._collect_guild_members(guild),
            )
            for member in members:
                identity = self._canonical_identity(member)
                identities.setdefault(str(identity.identity_key), identity)
            self._report_identity_scan_progress(
                0,
                f"Loaded {len(members)} cached/fetched members for guild "
                f"{(getattr(guild, 'name', None) or getattr(guild, 'id', 'unknown'))}.",
            )

        self._report_identity_scan_progress(
            0,
            "Discovering Discord channels and threads before scanning history...",
        )
        for conversation in self._discover_conversations():
            channel = self._conversation_channels[str(conversation.id)]
            if getattr(channel, "history", None) is None:
                continue
            channel_name = str(getattr(channel, "name", conversation.id))
            self._report_identity_scan_progress(
                self._identity_scan_messages_scanned,
                f"Scanning #{channel_name} ({conversation.id}) history...",
            )
            messages = self._run(
                self._collect_raw_messages(channel, identity_scan=True),
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

            # Reaction-user pagination can take substantially longer than the
            # message-history traversal above. Keep it in one coroutine per
            # channel and report its own progress instead of appearing idle
            # after the final historical-message counter.
            reaction_identities = self._run(
                self._collect_channel_reaction_identities(
                    messages,
                    channel_name=channel_name,
                ),
            )
            for identity in reaction_identities:
                identities.setdefault(str(identity.identity_key), identity)

        yield from (identities[key] for key in sorted(identities))

    def iter_identity_batches(
        self,
        *,
        resume_cursor: dict[str, Any] | None = None,
        batch_size: int = 100,
    ) -> Iterable[IdentityDiscoveryBatch]:
        """Discover identities available directly from Discord membership.

        Historical authors and reaction users are discovered during canonical
        message traversal, so identity bootstrap never scans message history.
        """
        if batch_size <= 0:
            raise ValueError("Identity discovery batch size must be greater than zero.")
        cursor = dict(resume_cursor or {})
        stage = str(cursor.get("stage", "members"))
        guilds = tuple(self._iter_guilds())
        if stage != "members":
            yield IdentityDiscoveryBatch(
                (),
                cursor={"stage": "canonical", "guild_index": len(guilds)},
                complete=True,
            )
            return
        guild_index = int(cursor.get("guild_index", 0))
        member_index = int(cursor.get("member_index", 0))
        batch: list[CanonicalIdentity] = []
        for current_guild_index in range(guild_index, len(guilds)):
            members = self._run(self._collect_guild_members(guilds[current_guild_index]))
            start_member = member_index if current_guild_index == guild_index else 0
            for current_member_index in range(start_member, len(members)):
                batch.append(self._canonical_identity(members[current_member_index]))
                if len(batch) >= batch_size:
                    yield IdentityDiscoveryBatch(
                        tuple(batch),
                        cursor={
                            "stage": "members",
                            "guild_index": current_guild_index,
                            "member_index": current_member_index + 1,
                        },
                    )
                    batch = []
            member_index = 0
        yield IdentityDiscoveryBatch(
            tuple(batch),
            cursor={"stage": "canonical", "guild_index": len(guilds)},
            complete=True,
        )

    @staticmethod
    async def _collect_raw_message_slice(
        channel: Any,
        start: int,
        limit: int,
    ) -> tuple[list[Any], bool]:
        history = channel.history(limit=None, oldest_first=True)
        messages: list[Any] = []
        index = 0
        async for message in history:
            if index < start:
                index += 1
                continue
            messages.append(message)
            index += 1
            if len(messages) >= limit:
                return messages, False
        return messages, True

    @staticmethod
    async def _collect_reaction_users(users: Any) -> list[Any]:
        return [user async for user in users(limit=None)]

    def iter_conversations(self) -> Iterable[CanonicalConversation]:
        """Yield message-bearing Discord channels and threads deterministically."""
        yield from self._discover_conversations()

    def _discover_conversations(self) -> list[CanonicalConversation]:
        conversations: dict[str, CanonicalConversation] = {}

        for guild in self._iter_guilds():
            channels = self._run(
                self._collect_message_bearing_channels(guild),
            )
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

    def iter_custom_emojis(self) -> Iterable[CanonicalCustomEmoji]:
        """Enumerate custom emojis required by the archive scope.

        The archive must preserve custom emojis that occur in reactions even
        when the emoji is owned by another guild. Discord permits a message
        in the configured guild to use an emoji from another shared guild, so
        enumerating only ``guild.emojis`` is insufficient.

        Identity discovery populates ``_message_cache`` before this method is
        called by the importer. We therefore combine authoritative guild
        emoji discovery with custom emojis encountered in cached reactions.
        """
        emojis: dict[str, Any] = {}

        for guild in self._iter_guilds():
            fetch_emojis = getattr(guild, "fetch_emojis", None)
            if callable(fetch_emojis):
                guild_emojis = self._run(fetch_emojis())
            else:
                guild_emojis = getattr(guild, "emojis", ())
            for emoji in guild_emojis or ():
                emoji_id = getattr(emoji, "id", None)
                if emoji_id is not None:
                    emojis[str(emoji_id)] = emoji

        # Reaction-only custom emojis are retained as lightweight emoji objects
        # while each message is canonicalized; raw messages themselves are not cached.
        emojis.update(self._custom_emoji_objects)

        # Preserve compatibility with callers that explicitly populated the
        # legacy raw-message cache. Normal streaming imports leave this cache
        # empty, so this path does not reintroduce unbounded retention.
        for messages in (
            *self._message_cache.values(),
            *self._incremental_message_cache.values(),
        ):
            for message in messages:
                for reaction in getattr(message, "reactions", ()) or ():
                    emoji = getattr(reaction, "emoji", None)
                    emoji_id = getattr(emoji, "id", None) if emoji is not None else None
                    if emoji_id is not None:
                        emojis.setdefault(str(emoji_id), emoji)

        for emoji_id in sorted(emojis):
            emoji = emojis[emoji_id]
            name = getattr(emoji, "name", None)
            if not name:
                continue
            # discord.py exposes the CDN URL as a string, while the emoji
            # object itself provides ``read()`` for retrieving the asset bytes.
            # Prefer the real discord.py API.  The URL-reader fallback is kept
            # for lightweight source doubles and older adapter integrations
            # whose URL object exposes an async ``read()`` method.
            read_emoji = getattr(emoji, "read", None)
            if callable(read_emoji):
                content = self._run(read_emoji())
            else:
                asset = getattr(emoji, "url", None)
                read_asset = getattr(asset, "read", None)
                if not callable(read_asset):
                    raise AdapterError(
                        f"Discord custom emoji {emoji_id} does not expose readable asset bytes."
                    )
                content = self._run(read_asset())
            digest = hashlib.sha256(content).hexdigest()
            self._custom_emoji_bytes[emoji_id] = bytes(content)
            animated = bool(getattr(emoji, "animated", False))
            yield CanonicalCustomEmoji(
                id=EmojiId(emoji_id),
                name=str(name),
                animated=animated,
                content_type="image/gif" if animated else "image/png",
                size=len(content),
                sha256=digest,
            )

    def custom_emoji_bytes(
        self,
        emoji: CanonicalCustomEmoji,
    ) -> bytes:
        try:
            return self._custom_emoji_bytes[str(emoji.id)]
        except KeyError as exc:
            raise AdapterError(
                f"Discord custom emoji bytes were not loaded for {emoji.id}."
            ) from exc

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
            pinned_ids = self._run(self._collect_pinned_ids(channel))
            for raw_message in cached_messages:
                yield self._canonicalize_one_cached_message(
                    raw_message,
                    pinned_ids,
                )
            return

        yield from self._iter_canonical_history(
            channel,
            conversation_id=str(conversation.id),
            cache=None,
        )

    def iter_messages_after_checkpoint(
        self,
        conversation: CanonicalConversation,
        cursor: SourceRefreshCursor,
    ) -> Iterable[CanonicalMessage]:
        """Resume full-history traversal after a committed message.

        Discord's history endpoint can constrain traversal by creation time,
        so recovery does not need to replay the entire channel. A tiny
        timestamp overlap handles messages sharing the checkpoint timestamp;
        canonical ordering then filters the already committed boundary.
        """
        channel = self._conversation_channels.get(str(conversation.id))
        if channel is None:
            raise NotFoundError(
                f"Discord conversation {conversation.id} is not available."
            )

        try:
            yield from self._iter_canonical_history(
                channel,
                conversation_id=str(conversation.id),
                cache=None,
                after=cursor.created_at - timedelta(microseconds=1),
                skip_through=cursor,
            )
        except TypeError:
            # Test doubles and older source clients may not expose the native
            # ``after`` argument. Preserve safe recovery semantics by falling
            # back to the existing complete traversal plus importer boundary.
            yield from self.iter_messages(conversation)

    def iter_identities_since(
        self,
        cursors: dict[str, SourceRefreshCursor],
    ) -> Iterable[CanonicalIdentity]:
        """Discover identities from only the incremental message windows."""
        identities: dict[str, CanonicalIdentity] = {}

        for guild in self._iter_guilds():
            members = self._run(self._collect_guild_members(guild))
            for member in members:
                identity = self._canonical_identity(member)
                identities.setdefault(str(identity.identity_key), identity)

        for conversation in self._discover_conversations():
            cursor = cursors.get(str(conversation.id))
            if cursor is None:
                continue
            channel = self._conversation_channels[str(conversation.id)]
            if getattr(channel, "history", None) is None:
                continue
            messages = self._run(
                self._collect_incremental_raw_messages(channel, cursor),
            )
            self._incremental_message_cache[str(conversation.id)] = tuple(messages)
            for message in messages:
                author = getattr(message, "author", None)
                if author is not None:
                    identity = self._canonical_identity(author)
                    identities.setdefault(str(identity.identity_key), identity)
                for reaction_group in getattr(message, "reactions", ()):
                    users = getattr(reaction_group, "users", None)
                    if users is None:
                        raise AdapterError(
                            "Discord reaction does not expose reacting users."
                        )
                    for identity in self._run(
                        self._collect_reaction_identities(users),
                    ):
                        identities.setdefault(str(identity.identity_key), identity)

        yield from (identities[key] for key in sorted(identities))

    def iter_pinned_message_ids(
        self,
        conversation: CanonicalConversation,
    ) -> Iterable[str] | None:
        """Return the complete current Discord pin set for one channel."""
        channel = self._conversation_channels.get(str(conversation.id))
        if channel is None:
            raise NotFoundError(
                f"Discord conversation {conversation.id} is not available."
            )
        pinned_ids = self._run(self._collect_pinned_ids(channel))
        return tuple(
            self._message_key(message_id)
            for message_id in sorted(pinned_ids)
        )

    def iter_messages_by_ids(
        self,
        conversation: CanonicalConversation,
        message_ids: Iterable[str],
    ) -> Iterable[CanonicalMessage]:
        """Fetch only requested reply targets instead of replaying channel history."""
        channel = self._conversation_channels.get(str(conversation.id))
        if channel is None:
            raise NotFoundError(
                f"Discord conversation {conversation.id} is not available."
            )
        fetch_message = getattr(channel, "fetch_message", None)
        if not callable(fetch_message):
            yield from super().iter_messages_by_ids(conversation, message_ids)
            return

        pinned_ids = self._run(self._collect_pinned_ids(channel))
        seen: set[str] = set()
        for canonical_id in message_ids:
            key = str(canonical_id)
            prefix = "discord:message:"
            if not key.startswith(prefix):
                continue
            raw_id = key[len(prefix):]
            if not raw_id or key in seen:
                continue
            seen.add(key)
            try:
                raw_message = self._run(fetch_message(int(raw_id)))
            except Exception as exc:
                # A deleted/unavailable target is left unresolved for the
                # coordinator's existing completion invariant to report.
                if exc.__class__.__name__ in {"NotFound", "UnknownMessage"}:
                    continue
                raise
            canonical = self._canonicalize_one_cached_message(raw_message, pinned_ids)
            if str(canonical.id) == key:
                yield canonical

    def iter_message_identities(
        self,
        message: CanonicalMessage,
    ) -> Iterable[CanonicalIdentity]:
        """Yield rich Discord identities observed during message canonicalization."""
        if self._current_message_id == self._message_key(message.id):
            return self._current_message_identities
        return ()

    def iter_messages_since(
        self,
        conversation: CanonicalConversation,
        cursor: SourceRefreshCursor,
    ) -> Iterable[CanonicalMessage]:
        """Yield messages from Discord's bounded incremental history window."""
        channel = self._conversation_channels.get(str(conversation.id))
        if channel is None:
            raise NotFoundError(
                f"Discord conversation {conversation.id} is not available."
            )

        cached_messages = self._incremental_message_cache.get(str(conversation.id))
        if cached_messages is not None:
            pinned_ids = self._run(self._collect_pinned_ids(channel))
            for raw_message in cached_messages:
                yield self._canonicalize_one_cached_message(raw_message, pinned_ids)
            return

        yield from self._iter_canonical_history(
            channel,
            conversation_id=str(conversation.id),
            cache=None,
            after=cursor.created_at - self._incremental_lookback,
        )

    def _iter_canonical_history(
        self,
        channel: Any,
        *,
        conversation_id: str,
        cache: dict[str, tuple[Any, ...]] | None,
        after: datetime | None = None,
        skip_through: SourceRefreshCursor | None = None,
    ) -> Iterable[CanonicalMessage]:
        """Stream Discord history one message at a time through the sync boundary."""
        history_kwargs: dict[str, Any] = {
            "limit": None,
            "oldest_first": True,
        }
        if after is not None:
            history_kwargs["after"] = after
        history = channel.history(**history_kwargs)
        iterator = history.__aiter__()
        pinned_ids = self._run(self._collect_pinned_ids(channel))
        cached: list[Any] = list(cache.get(conversation_id, ())) if cache is not None else []
        cached_ids = {str(getattr(item, "id", "")) for item in cached}
        try:
            while True:
                try:
                    raw_message = self._next_history_message_with_retry(iterator)
                except StopAsyncIteration:
                    break

                raw_message_id = str(getattr(raw_message, "id", ""))
                if cache is not None:
                    if raw_message_id not in cached_ids:
                        cached.append(raw_message)
                        cached_ids.add(raw_message_id)
                        cache[conversation_id] = tuple(cached)

                canonical = self._canonicalize_one_cached_message(
                    raw_message,
                    pinned_ids,
                )
                if skip_through is not None and (
                    canonical.created_at,
                    str(canonical.id),
                ) <= (
                    skip_through.created_at,
                    str(skip_through.message_id),
                ):
                    continue
                yield canonical
        finally:
            close = getattr(iterator, "aclose", None)
            if callable(close):
                self._close_async_iterator(close)

    def _next_history_message_with_retry(self, iterator: Any) -> Any:
        """Fetch one history item, retrying transient Discord HTTP failures.

        discord.py already retries individual HTTP requests, but a persistent
        upstream 5xx/transport failure is ultimately surfaced as
        ``DiscordServerError``.  Historical imports are intentionally
        checkpointed per message, so treating one transient history-page
        failure as fatal would unnecessarily terminate a multi-day import.
        Retrying the iterator's next request is safe because discord.py only
        advances its history cursor after a successful response.
        """
        for attempt in range(1, self._history_retry_attempts + 1):
            try:
                return self._run(iterator.__anext__())
            except Exception as exc:
                if not self._is_retryable_history_error(exc):
                    raise
                if attempt >= self._history_retry_attempts:
                    raise
                delay = min(
                    self._history_retry_base_delay * (2 ** (attempt - 1)),
                    self._history_retry_max_delay,
                )
                time.sleep(delay)
        raise AssertionError("history retry loop exited unexpectedly")

    @staticmethod
    def _is_retryable_history_error(exc: BaseException) -> bool:
        """Return whether a Discord history request failure is transient."""
        status = getattr(exc, "status", None)
        try:
            status = int(status)
        except (TypeError, ValueError):
            status = None
        if status is not None and 500 <= status <= 599:
            return True
        # Keep this fallback deliberately narrow: discord.py's concrete
        # DiscordServerError exposes status=5xx, while test doubles and some
        # wrapped transports may only preserve the exception class name.
        return exc.__class__.__name__ == "DiscordServerError"

    def _close_async_iterator(self, close: Callable[[], Awaitable[Any]]) -> None:
        """Best-effort cleanup for an async iterator during interrupted import.

        The Discord runtime owns the event loop and closes it after an import
        exits. Python may finalize this generator after that runtime cleanup,
        so an unconditional ``run_until_complete(aclose())`` can turn a
        harmless KeyboardInterrupt into a secondary ``Event loop is closed``
        traceback.
        """
        awaitable = close()
        runner = self._runner
        loop = getattr(runner, "__self__", None) if runner is not None else None
        if loop is not None and getattr(loop, "is_closed", lambda: False)():
            close_awaitable = getattr(awaitable, "close", None)
            if callable(close_awaitable):
                close_awaitable()
            return
        try:
            self._run(awaitable)
        except RuntimeError as exc:
            if "event loop is closed" not in str(exc).lower():
                raise
            close_awaitable = getattr(awaitable, "close", None)
            if callable(close_awaitable):
                close_awaitable()

    def _canonicalize_one_cached_message(
        self,
        raw_message: Any,
        pinned_ids: set[str],
    ) -> CanonicalMessage:
        return self._run(
            self._canonical_message(
                raw_message,
                pinned_ids=pinned_ids,
            )
        )

    @classmethod
    async def _collect_raw_messages_after_checkpoint(
        cls,
        channel: Any,
        cursor: SourceRefreshCursor,
    ) -> list[Any]:
        after = cursor.created_at - timedelta(microseconds=1)
        history = channel.history(
            limit=None,
            oldest_first=True,
            after=after,
        )
        return [message async for message in history]

    async def _collect_incremental_raw_messages(
        cls,
        channel: Any,
        cursor: SourceRefreshCursor,
    ) -> list[Any]:
        after = cursor.created_at - cls._incremental_lookback
        history = channel.history(
            limit=None,
            oldest_first=True,
            after=after,
        )
        return [message async for message in history]

    def attachment_bytes(
        self,
        attachment: CanonicalAttachment,
    ) -> bytes:
        """Return bytes previously acquired while importing the message."""
        try:
            payload = self._attachment_bytes[attachment.sha256]
        except KeyError as exc:
            raise NotFoundError(
                f"Discord attachment {attachment.id} is not available."
            ) from exc
        self._attachment_bytes.pop(attachment.sha256, None)
        self._attachment_cache_bytes = sum(map(len, self._attachment_bytes.values()))
        return payload

    def release_attachment_bytes(
        self,
        attachment: CanonicalAttachment,
    ) -> None:
        """Release cached bytes once the importer has finished this attachment."""
        payload = self._attachment_bytes.pop(attachment.sha256, None)
        if payload is not None:
            self._attachment_cache_bytes -= len(payload)

    async def _collect_raw_messages(
        self,
        channel: Any,
        *,
        identity_scan: bool = False,
    ) -> list[Any]:
        """Collect a complete channel history, optionally reporting progress."""
        history = channel.history(
            limit=None,
            oldest_first=True,
        )
        messages: list[Any] = []
        async for message in history:
            messages.append(message)
            if identity_scan:
                self._identity_scan_messages_scanned += 1
                self._report_identity_scan_progress(
                    self._identity_scan_messages_scanned,
                    f"Scanning Discord history in #{(getattr(channel, 'name', None) or getattr(channel, 'id', 'unknown'))}",
                )
        return messages

    async def _canonicalize_cached_messages(
        self,
        messages: tuple[Any, ...],
        channel: Any,
    ) -> list[CanonicalMessage]:
        pinned_ids = await self._collect_pinned_ids(channel)
        result: list[CanonicalMessage] = []
        for message in messages:
            result.append(await self._canonical_message(message, pinned_ids=pinned_ids))
        return result

    async def _collect_messages(
        self,
        channel: Any,
    ) -> list[CanonicalMessage]:
        messages = await self._collect_raw_messages(channel)
        return await self._canonicalize_cached_messages(
            tuple(messages),
            channel,
        )

    async def _collect_channel_reaction_identities(
        self,
        messages: Iterable[Any],
        *,
        channel_name: str,
    ) -> list[CanonicalIdentity]:
        """Collect historical reaction actors while reporting API pagination.

        Message history and reaction-user history are separate Discord API
        traversals. In particular, ``Reaction.users(limit=None)`` may paginate
        many users after message scanning has already reached the end of a
        channel. Progress here makes that work observable without truncating
        the canonical identity set.
        """
        message_list = tuple(messages)
        reaction_count = sum(
            len(getattr(message, "reactions", ()) or ())
            for message in message_list
        )
        identities: dict[str, CanonicalIdentity] = {}
        reactions_scanned = 0
        users_scanned = 0
        self._report_identity_scan_progress(
            0,
            f"Resolving reaction users in #{channel_name} "
            f"({reaction_count} reaction groups across {len(message_list)} messages)...",
        )

        for message in message_list:
            for reaction_group in getattr(message, "reactions", ()) or ():
                users = getattr(reaction_group, "users", None)
                if users is None:
                    raise AdapterError(
                        "Discord reaction does not expose reacting users."
                    )
                async for user in users(limit=None):
                    identity = self._canonical_identity(user)
                    identities.setdefault(str(identity.identity_key), identity)
                    users_scanned += 1
                    if users_scanned % 100 == 0:
                        self._report_identity_scan_progress(
                            0,
                            f"Resolved {users_scanned} reaction users in "
                            f"#{channel_name}; processed {reactions_scanned} "
                            f"of {reaction_count} reaction groups...",
                        )
                reactions_scanned += 1
                if reactions_scanned % 25 == 0:
                    self._report_identity_scan_progress(
                        0,
                        f"Processed {reactions_scanned} of {reaction_count} "
                        f"reaction groups in #{channel_name}; discovered "
                        f"{users_scanned} reaction users...",
                    )

        self._report_identity_scan_progress(
            0,
            f"Finished reaction identity discovery in #{channel_name}: "
            f"{reactions_scanned} reaction groups and {users_scanned} users.",
        )
        return list(identities.values())

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
        for attachment in self._source_attachments(message):
            attachments_list.append(
                await self._canonical_attachment(attachment)
            )
        attachments = tuple(attachments_list)
        message_identities: list[CanonicalIdentity] = [self._canonical_identity(author)]
        reactions_list: list[CanonicalReaction] = []
        for reaction_group in getattr(message, "reactions", ()):
            reactions_list.extend(
                await self._canonical_reactions(
                    reaction_group,
                    identity_sink=message_identities,
                )
            )
        reactions = tuple(reactions_list)
        unique_identities = {
            str(identity.identity_key): identity
            for identity in message_identities
        }
        self._current_message_id = self._message_key(message_id)
        self._current_message_identities = tuple(unique_identities.values())
        for reaction_group in getattr(message, "reactions", ()) or ():
            emoji = getattr(reaction_group, "emoji", None)
            emoji_id = getattr(emoji, "id", None) if emoji is not None else None
            if emoji_id is not None:
                self._custom_emoji_objects.setdefault(str(emoji_id), emoji)

        reply_to = self._canonical_reply_to(message)

        canonical_id = MessageId(
            self._message_key(message_id),
        )
        canonical_conversation_id = ConversationId(
            self._conversation_key_from_channel_id(
                conversation_id,
            ),
        )
        content = self._canonical_content(message)

        try:
            return CanonicalMessage(
                id=canonical_id,
                conversation_id=canonical_conversation_id,
                identity_key=message_identities[0].identity_key,
                content=content,
                created_at=created_at,
                edited_at=getattr(message, "edited_at", None),
                reply_to=reply_to,
                pinned=str(message_id) in pinned_ids,
                attachments=attachments,
                reactions=reactions,
            )
        except ValueError as exc:
            raise AdapterError(
                self._message_representability_error(
                    message,
                    canonical_id=canonical_id,
                    canonical_conversation_id=canonical_conversation_id,
                    content=content,
                    attachments=attachments,
                    cause=exc,
                )
            ) from exc

    @staticmethod
    def _message_representability_error(
        message: Any,
        *,
        canonical_id: MessageId,
        canonical_conversation_id: ConversationId,
        content: str,
        attachments: tuple[CanonicalAttachment, ...],
        cause: ValueError,
    ) -> str:
        """Describe why one Discord message cannot enter the canonical model.

        This deliberately reports source-side observations rather than
        inventing a canonical representation.  The resulting diagnostic is
        intended to identify the first real-world source feature that needs a
        concrete canonical-model decision.
        """
        details = [
            f"Discord message {canonical_id}",
            f"conversation {canonical_conversation_id}",
            f"content_length={len(content)}",
            f"attachments={len(attachments)}",
        ]

        for attribute in (
            "embeds",
            "stickers",
            "components",
            "message_snapshots",
            "poll",
            "call",
            "activity",
            "purchase_notification",
        ):
            value = getattr(message, attribute, None)
            if value is not None:
                try:
                    details.append(f"{attribute}={len(value)}")
                except TypeError:
                    details.append(f"{attribute}=present")

        message_type = getattr(message, "type", None)
        if message_type is not None:
            type_name = getattr(message_type, "name", None)
            details.append(
                f"message_type={type_name or str(message_type)}"
            )

        # The normal diagnostic remains compact enough for a CLI error, but
        # an actual Discord message can carry source features that are not
        # obvious from the canonical model (for example flags, interaction
        # metadata, or newly introduced discord.py fields).  Expose a stable
        # object-level fingerprint when requested so an integration failure
        # can be diagnosed from the real source object instead of guessing
        # which Discord feature was present.  This is intentionally opt-in
        # because repr(message) can be large and may contain source data.
        details.extend(
            [
                f"source_class={type(message).__name__}",
                f"source_module={type(message).__module__}",
                f"content_repr={content!r}",
                f"system_content_repr={str(getattr(message, 'system_content', '') or '')!r}",
                f"message_type_repr={message_type!r}",
                f"flags_repr={getattr(message, 'flags', None)!r}",
                f"source_dict_keys={sorted(getattr(message, '__dict__', {}).keys())!r}",
            ]
        )

        if os.environ.get("ARCHIVE_SYNC_ENGINE_DISCORD_DEBUG_MESSAGES"):
            details.extend(
                [
                    f"source_content={getattr(message, 'content', None)!r}",
                    f"source_system_content={getattr(message, 'system_content', None)!r}",
                    f"source_attachments={getattr(message, 'attachments', None)!r}",
                    f"source_embeds={getattr(message, 'embeds', None)!r}",
                    f"source_stickers={getattr(message, 'stickers', None)!r}",
                    f"source_components={getattr(message, 'components', None)!r}",
                    f"source_snapshots={getattr(message, 'message_snapshots', None)!r}",
                    f"source_poll={getattr(message, 'poll', None)!r}",
                    f"source_call={getattr(message, 'call', None)!r}",
                    f"source_activity={getattr(message, 'activity', None)!r}",
                    f"source_purchase_notification={getattr(message, 'purchase_notification', None)!r}",
                    f"source_interaction={getattr(message, 'interaction', None)!r}",
                    f"source_interaction_metadata={getattr(message, 'interaction_metadata', None)!r}",
                    f"source_application={getattr(message, 'application', None)!r}",
                    f"source_flags={getattr(message, 'flags', None)!r}",
                ]
            )

        return (
            f"{'; '.join(details)}: {cause}. "
            "The Discord source message is not representable by the current "
            "canonical message model; no source content was discarded."
        )

    @staticmethod
    def _source_attachments(message: Any) -> tuple[Any, ...]:
        """Return message attachments, including attachments in snapshots.

        Discord message forwarding uses ``Message.message_snapshots`` for the
        forwarded source message.  A forwarded message can therefore expose
        no attachments on the outer ``Message`` while the snapshot contains
        the source attachment(s).  Treat those snapshot attachments as source
        input rather than allowing the canonical message invariant to reject
        an otherwise representable message.
        """
        attachments: list[Any] = list(
            getattr(message, "attachments", ()) or ()
        )
        seen_ids = {
            str(attachment_id)
            for attachment_id in (
                getattr(attachment, "id", None)
                for attachment in attachments
            )
            if attachment_id is not None
        }

        for snapshot in getattr(message, "message_snapshots", ()) or ():
            for attachment in getattr(snapshot, "attachments", ()) or ():
                attachment_id = getattr(attachment, "id", None)
                if attachment_id is None or str(attachment_id) not in seen_ids:
                    attachments.append(attachment)
                    if attachment_id is not None:
                        seen_ids.add(str(attachment_id))

        return tuple(attachments)

    @staticmethod
    def _canonical_content(message: Any) -> str:
        """Return the best platform-provided textual representation.

        Discord system messages normally expose a human-readable
        ``system_content`` value.  Some system-event messages, however, can
        legitimately arrive with both ``content`` and ``system_content``
        empty.  The canonical message model requires textual or attachment
        content, so for the currently observed ``pins_add`` event we derive
        the smallest deterministic textual representation from the source
        event itself rather than dropping the event or inventing unrelated
        content.
        """
        content = str(getattr(message, "content", "") or "")
        if content:
            return content

        system_content = str(getattr(message, "system_content", "") or "")
        if system_content:
            return system_content

        message_type = getattr(message, "type", None)
        type_name = getattr(message_type, "name", None)
        if type_name == "pins_add":
            author = getattr(message, "author", None)
            author_name = (
                getattr(author, "global_name", None)
                or getattr(author, "display_name", None)
                or getattr(author, "name", None)
            )
            if author_name:
                return f"{author_name} pinned a message."
            return "A message was pinned."

        embed_content = DiscordSourceAdapter._canonical_embed_content(
            getattr(message, "embeds", ()) or (),
        )
        if embed_content:
            return embed_content

        snapshot_content = DiscordSourceAdapter._canonical_snapshot_content(
            getattr(message, "message_snapshots", ()) or (),
        )
        if snapshot_content:
            return snapshot_content

        sticker_content = DiscordSourceAdapter._canonical_sticker_content(
            getattr(message, "stickers", ()) or (),
        )
        if sticker_content:
            return sticker_content

        component_content = DiscordSourceAdapter._canonical_component_content(
            getattr(message, "components", ()) or (),
        )
        if component_content:
            return component_content

        poll_content = DiscordSourceAdapter._canonical_poll_content(
            getattr(message, "poll", None),
        )
        if poll_content:
            return poll_content

        # These Discord message features are also first-class source content,
        # but the canonical model has no dedicated fields for them.  Preserve
        # their existence rather than letting an otherwise meaningful source
        # message become an empty canonical message.
        for attribute, label in (
            ("call", "call"),
            ("activity", "activity"),
            ("purchase_notification", "purchase notification"),
        ):
            if getattr(message, attribute, None) is not None:
                return f"[Discord {label} message]"

        # Some Discord messages contain a first-class source feature whose
        # detailed fields are not exposed by the current canonical model (or
        # whose discord.py representation has changed between releases).  A
        # non-empty feature collection is still meaningful source content.
        # Preserve that fact with an explicit deterministic marker instead of
        # converting the message into an empty canonical message and aborting
        # the entire import.  The marker is deliberately feature-specific so
        # it is clear that this is a lossless *existence* representation, not
        # invented user-authored text.
        for attribute, label in (
                ("embeds", "embed"),
                ("stickers", "sticker"),
                ("components", "interactive"),
                ("message_snapshots", "forwarded"),
        ):
            value = getattr(message, attribute, None)
            if value:
                return f"[Discord {label} message]"

        # Interaction metadata can accompany otherwise content-less Discord
        # messages even when ``interaction`` itself is absent.  Treat it as a
        # source feature for the same reason.

        # Check for the modern attribute first (discord.py 2.4+)
        if hasattr(message, "interaction_metadata"):
            if getattr(message, "interaction_metadata", None) is not None:
                return "[Discord interaction message]"
        # Fallback for older library versions that only have the deprecated attribute
        elif getattr(message, "interaction", None) is not None:
            return "[Discord interaction message]"

        # Discord has added message-level source structures over time.  Keep a
        # small compatibility set here for fields that are meaningful on an
        # otherwise content-less message but are not modeled independently by
        # the canonical schema.  This prevents a discord.py upgrade from
        # turning a newly populated source field into an import-fatal empty
        # message.
        for attribute, label in (
            ("role_subscription_data", "role subscription"),
            ("application", "application"),
            ("application_id", "application"),
            ("webhook_id", "webhook"),
        ):
            if getattr(message, attribute, None) is not None:
                return f"[Discord {label} message]"

        # Discord can expose system/event messages whose ``system_content``
        # is empty even though the message has a meaningful non-default
        # message type.  Do not let such source events abort the entire
        # archive import.  At this point all richer source representations
        # above have already been exhausted, so the event type itself is the
        # only stable source information available to this canonical model.
        # Keep ordinary ``default`` messages strict: an actually empty
        # user-authored message remains unrepresentable unless it has an
        # attachment.
        if type_name and type_name != "default":
            return f"[Discord system message: {type_name}]"

        return ""

    @staticmethod
    def _canonical_embed_content(embeds: Any) -> str:
        """Extract stable human-readable content from Discord embeds.

        The canonical message model does not have a separate embed field.
        Embed-only Discord messages therefore need a deterministic textual
        representation so their source content is not silently discarded.
        Empty/metadata-only embeds still return an empty string and remain
        explicitly unrepresentable rather than inventing content.
        """
        lines: list[str] = []

        for embed in embeds:
            def value(name: str) -> str:
                raw = getattr(embed, name, None)
                if raw is None and isinstance(embed, dict):
                    raw = embed.get(name)
                return str(raw or "").strip()

            title = value("title")
            description = value("description")
            url = value("url")
            if title:
                lines.append(title)
            if description:
                lines.append(description)
            if url:
                lines.append(url)

            author = getattr(embed, "author", None)
            if author is None and isinstance(embed, dict):
                author = embed.get("author")
            author_name = ""
            author_url = ""
            if isinstance(author, dict):
                author_name = str(author.get("name") or "").strip()
                author_url = str(author.get("url") or "").strip()
            elif author is not None:
                author_name = str(getattr(author, "name", "") or "").strip()
                author_url = str(getattr(author, "url", "") or "").strip()
            if author_name:
                lines.append(author_name)
            if author_url:
                lines.append(author_url)

            fields = getattr(embed, "fields", None)
            if fields is None and isinstance(embed, dict):
                fields = embed.get("fields")
            for field in fields or ():
                if isinstance(field, dict):
                    field_name = str(field.get("name") or "").strip()
                    field_value = str(field.get("value") or "").strip()
                else:
                    field_name = str(getattr(field, "name", "") or "").strip()
                    field_value = str(getattr(field, "value", "") or "").strip()
                if field_name:
                    lines.append(field_name)
                if field_value:
                    lines.append(field_value)

            footer = getattr(embed, "footer", None)
            if footer is None and isinstance(embed, dict):
                footer = embed.get("footer")
            footer_text = ""
            if isinstance(footer, dict):
                footer_text = str(footer.get("text") or "").strip()
            elif footer is not None:
                footer_text = str(getattr(footer, "text", "") or "").strip()
            if footer_text:
                lines.append(footer_text)

            for media_name in ("image", "thumbnail"):
                media = getattr(embed, media_name, None)
                if media is None and isinstance(embed, dict):
                    media = embed.get(media_name)
                media_url = ""
                if isinstance(media, dict):
                    media_url = str(media.get("url") or "").strip()
                elif media is not None:
                    media_url = str(getattr(media, "url", "") or "").strip()
                if media_url:
                    lines.append(media_url)

        return "\n".join(line for line in lines if line)

    @staticmethod
    def _canonical_snapshot_content(snapshots: Any) -> str:
        """Extract canonical text from Discord forwarded-message snapshots."""
        lines: list[str] = []

        for snapshot in snapshots:
            content = str(getattr(snapshot, "content", "") or "").strip()
            if content:
                lines.append(content)

            system_content = str(
                getattr(snapshot, "system_content", "") or ""
            ).strip()
            if system_content and system_content != content:
                lines.append(system_content)

            embeds = DiscordSourceAdapter._canonical_embed_content(
                getattr(snapshot, "embeds", ()) or (),
            )
            if embeds:
                lines.append(embeds)

            stickers = DiscordSourceAdapter._canonical_sticker_content(
                getattr(snapshot, "stickers", ()) or (),
            )
            if stickers:
                lines.append(stickers)

            components = DiscordSourceAdapter._canonical_component_content(
                getattr(snapshot, "components", ()) or (),
            )
            if components:
                lines.append(components)

        return "\n".join(lines)

    @staticmethod
    def _canonical_sticker_content(stickers: Any) -> str:
        lines: list[str] = []
        for sticker in stickers:
            name = str(getattr(sticker, "name", "") or "").strip()
            if not name and isinstance(sticker, dict):
                name = str(sticker.get("name") or "").strip()
            if name:
                lines.append(f"[Sticker: {name}]")
        return "\n".join(lines)

    @staticmethod
    def _canonical_poll_content(poll: Any) -> str:
        """Extract deterministic textual content from a Discord poll.

        Discord polls are first-class message content in discord.py, but the
        canonical message model intentionally has no separate poll field.
        Preserve the poll's human-readable question and answer labels as
        canonical text rather than allowing an otherwise content-bearing
        message to fail the canonical message invariant.

        The helper accepts the concrete discord.py objects as well as simple
        mapping/object test doubles so the source adapter remains easy to
        exercise without importing discord.py in unit tests.
        """
        if poll is None:
            return ""

        def read(value: Any, name: str) -> Any:
            raw = getattr(value, name, None)
            if raw is None and isinstance(value, dict):
                raw = value.get(name)
            return raw

        question = read(poll, "question")
        question_text = read(question, "text") if question is not None else None
        if question_text is None and isinstance(question, str):
            question_text = question
        question_text = str(question_text or "").strip()

        lines: list[str] = []
        if question_text:
            lines.append(f"Poll: {question_text}")
        else:
            lines.append("Poll")

        answers = read(poll, "answers") or ()
        for answer in answers:
            answer_text = read(answer, "text")
            if answer_text is None:
                media = read(answer, "media")
                answer_text = read(media, "text") if media is not None else None
            answer_text = str(answer_text or "").strip()
            if answer_text:
                lines.append(f"- {answer_text}")

        return "\n".join(lines)

    @staticmethod
    def _canonical_component_content(components: Any) -> str:
        labels: list[str] = []
        for row in components:
            children = getattr(row, "children", None)
            if children is None and isinstance(row, dict):
                children = row.get("components")
            for component in children or ():
                label = str(
                    getattr(component, "label", None)
                    or (component.get("label") if isinstance(component, dict) else "")
                    or ""
                ).strip()
                url = str(
                    getattr(component, "url", None)
                    or (component.get("url") if isinstance(component, dict) else "")
                    or ""
                ).strip()
                if label:
                    labels.append(label)
                if url:
                    labels.append(url)
        return "\n".join(labels)

    def _canonical_reply_to(
        self,
        message: Any,
    ) -> MessageId | None:
        """Translate a Discord message reference without resolving its target.

        The canonical model stores the logical identity of the reply target,
        not a copied target message. Discord may expose the reference ID even
        when ``referenced_message`` is unavailable or the target was deleted.
        That distinction is important for archival fidelity: an unresolved
        reference is still canonical source data and must not be silently
        converted to ``None``.
        """
        reference = getattr(message, "reference", None)
        reply_message_id = getattr(reference, "message_id", None)
        if reply_message_id is None:
            return None

        return MessageId(
            self._message_key(reply_message_id),
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

        data = await self._read_attachment_with_retry(reader)
        digest = hashlib.sha256(data).hexdigest()
        payload = bytes(data)
        if digest not in self._attachment_bytes and len(payload) <= self._attachment_cache_limit:
            self._attachment_bytes[digest] = payload
            self._attachment_cache_bytes += len(payload)
            while self._attachment_cache_bytes > self._attachment_cache_limit and self._attachment_bytes:
                evicted_digest = next(iter(self._attachment_bytes))
                if evicted_digest == digest and len(self._attachment_bytes) > 1:
                    evicted_digest = next(key for key in self._attachment_bytes if key != digest)
                evicted = self._attachment_bytes.pop(evicted_digest)
                self._attachment_cache_bytes -= len(evicted)

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

    async def _read_attachment_with_retry(
        self,
        reader: Callable[[], Awaitable[bytes]],
    ) -> bytes:
        """Retry transient CDN payload truncation and transport failures.

        Attachment reads are idempotent GETs. A truncated response such as
        aiohttp.ClientPayloadError/ContentLengthError can therefore be retried
        without affecting the import checkpoint. Exhaustion still raises so
        the normal import checkpoint can be resumed later.
        """
        for attempt in range(1, self._attachment_retry_attempts + 1):
            try:
                return await reader()
            except Exception as exc:
                if not self._is_retryable_attachment_error(exc):
                    raise
                if attempt >= self._attachment_retry_attempts:
                    raise
                delay = min(
                    self._attachment_retry_base_delay * (2 ** (attempt - 1)),
                    self._attachment_retry_max_delay,
                )
                await asyncio.sleep(delay)
        raise AssertionError("attachment retry loop exited unexpectedly")

    @staticmethod
    def _is_retryable_attachment_error(exc: BaseException) -> bool:
        """Recognize transient HTTP/CDN errors without masking model errors."""
        status = getattr(exc, "status", None)
        try:
            status = int(status)
        except (TypeError, ValueError):
            status = None
        if status is not None and 500 <= status <= 599:
            return True
        retryable_names = {
            "ClientPayloadError", "ContentLengthError", "ServerDisconnectedError",
            "ClientConnectionError", "ConnectionResetError", "TimeoutError",
            "ServerTimeoutError", "ClientOSError",
        }
        return exc.__class__.__name__ in retryable_names or isinstance(
            exc, (ConnectionError, TimeoutError, OSError)
        )

    async def _canonical_reactions(
        self,
        reaction: Any,
        *,
        identity_sink: list[CanonicalIdentity] | None = None,
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
            if identity_sink is not None:
                identity_sink.append(identity)
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
                try:
                    guild = self._run(
                        self._client.fetch_guild(guild_id)
                    )
                except Exception as exc:
                    # discord.py raises NotFound (HTTP 404, Discord code
                    # 10004) when this bot cannot resolve the configured guild.
                    # Translate only this known resource error; authentication,
                    # network, and unexpected failures must retain their meaning.
                    if (
                        getattr(exc, "status", None) == 404
                        and getattr(exc, "code", None) == 10004
                    ):
                        raise NotFoundError(
                            f"Discord guild {guild_id} was not found or is not "
                            "accessible to this bot. Verify discord.guild_id in "
                            "the config is the server's numeric ID and that the "
                            "configured bot account is a member of that server."
                        ) from exc
                    raise

            if guild is None:
                raise NotFoundError(
                    f"Discord guild {guild_id} was not found."
                )

            yield guild

    @staticmethod
    async def _collect_guild_members(guild: Any) -> list[Any]:
        """Return the complete available guild member set.

        Prefer the populated discord.py member cache.  When the cache is
        unavailable, use Discord's explicit ``fetch_members(limit=None)``
        API rather than silently treating the guild as having no members.
        This keeps identity completeness a source-adapter concern while
        preserving the canonical importer contract.
        """
        members = getattr(guild, "members", None)
        if members is not None:
            return list(members)

        fetch_members = getattr(guild, "fetch_members", None)
        if fetch_members is None:
            raise AuthorizationError(
                "Discord guild member data is unavailable."
            )

        iterator = fetch_members(limit=None)
        if not hasattr(iterator, "__aiter__"):
            raise AdapterError(
                "Discord guild member fetch does not expose an async iterator."
            )

        return [member async for member in iterator]

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

    @classmethod
    async def _collect_message_bearing_channels(cls, guild: Any) -> list[Any]:
        """Collect message-bearing channels and active threads, including uncached ones."""
        channels = list(getattr(guild, "channels", ()) or ())
        threads = list(getattr(guild, "threads", ()) or ())

        if not channels:
            fetch_channels = getattr(guild, "fetch_channels", None)
            if fetch_channels is not None:
                fetched = fetch_channels()
                if hasattr(fetched, "__aiter__"):
                    channels = [channel async for channel in fetched]
                else:
                    channels = list(await fetched)

        if not threads:
            fetch_active_threads = getattr(guild, "fetch_active_threads", None)
            if fetch_active_threads is not None:
                result = fetch_active_threads()
                if hasattr(result, "__await__"):
                    result = await result
                threads = list(getattr(result, "threads", result) or ())

        candidates = (*channels, *threads)
        seen_ids: set[str] = set()
        result: list[Any] = []
        for channel in candidates:
            if not cls._is_message_bearing_channel(channel):
                continue
            channel_id = getattr(channel, "id", None)
            if channel_id is None:
                continue
            key = str(channel_id)
            if key in seen_ids:
                continue
            seen_ids.add(key)
            result.append(channel)
        return result

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

    def set_runner(self, runner: Callable[[Awaitable[Any]], Any] | None) -> None:
        """Set the event-loop runner used by synchronous adapter operations.

        The Discord runtime owns the event loop because the discord.py HTTP
        client and its aiohttp session are bound to that loop.  The adapter
        remains synchronous at its public boundary, so the runtime injects
        its ``run_until_complete`` runner rather than allowing individual
        adapter calls to create and close unrelated event loops.
        """
        self._runner = runner

    def _run(self, awaitable: Awaitable[_T]) -> _T:
        """Execute one Discord coroutine for the synchronous SourceAdapter contract."""
        if self._runner is not None:
            return self._runner(awaitable)

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
