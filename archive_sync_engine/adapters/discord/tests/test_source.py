from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from archive_sync_engine.adapters import DiscordSourceAdapter
from archive_sync_engine.adapters.exceptions import AdapterError, NotFoundError
from archive_sync_engine.models import CanonicalAttachment, ConversationType
from archive_sync_engine.models.ids import AttachmentId


class FakeUser:
    def __init__(self, user_id: int, name: str, bot: bool = False) -> None:
        self.id = user_id
        self.name = name
        self.global_name = None
        self.bot = bot


class FakeMember:
    def __init__(self, user: FakeUser, display_name: str) -> None:
        self._user = user
        self.display_name = display_name
        self.display_avatar = SimpleNamespace(
            url=f"https://cdn.example/{user.id}.png",
        )


class FakeChannel:
    def __init__(
        self,
        channel_id: int,
        name: str,
        position: int,
        created_at: datetime,
    ) -> None:
        self.id = channel_id
        self.name = name
        self.position = position
        self.created_at = created_at
        self.type = SimpleNamespace(name="text")
        self._archived_threads: dict[bool, tuple[FakeThread, ...]] = {
            False: (),
            True: (),
        }

    def archived_threads(self, *, private=False, joined=False, limit=None):
        async def iterator():
            for thread in self._archived_threads[private]:
                yield thread

        return iterator()


class FakeThread:
    def __init__(
        self,
        channel_id: int,
        name: str,
        parent_id: int,
        position: int,
        created_at: datetime,
    ) -> None:
        self.id = channel_id
        self.name = name
        self.parent_id = parent_id
        self.position = position
        self.created_at = created_at
        self.type = SimpleNamespace(name="public_thread")


class FakeGuild:
    def __init__(self) -> None:
        self.id = 123
        self.members = [
            FakeMember(FakeUser(2, "Bob"), "Bobby"),
            FakeMember(FakeUser(1, "Alice"), "Alice"),
            FakeMember(FakeUser(2, "Bob"), "Bobby"),
        ]
        created = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.channels = [
            FakeChannel(20, "second", 2, created),
            FakeThread(30, "thread", 20, 30, created),
            FakeChannel(10, "first", 1, created),
        ]


class FakeClient:
    def __init__(self, guild: FakeGuild) -> None:
        self.guild = guild

    def get_guild(self, guild_id: int):
        if guild_id == self.guild.id:
            return self.guild
        return None

    async def fetch_guild(self, guild_id: int):
        return None


def test_iter_identities_deduplicates_and_orders_users() -> None:
    adapter = DiscordSourceAdapter(
        FakeClient(FakeGuild()),
        [123],
    )

    identities = list(adapter.iter_identities())

    assert [str(item.identity_key) for item in identities] == [
        "discord:user:1",
        "discord:user:2",
    ]
    assert identities[1].display_name == "Bobby"
    assert identities[0].avatar_url == "https://cdn.example/1.png"



def test_iter_identities_fetches_members_when_cache_is_unavailable() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    guild = FakeGuild()
    guild.members = None

    fetch_limits = []

    async def fetch_members(*, limit=None):
        fetch_limits.append(limit)
        for member in (
            FakeMember(FakeUser(3, "Carol"), "Carol"),
            FakeMember(FakeUser(4, "Dave"), "Dave"),
        ):
            yield member

    guild.fetch_members = fetch_members
    guild.channels = [
        FakeChannel(10, "first", 1, created),
    ]

    adapter = DiscordSourceAdapter(
        FakeClient(guild),
        [123],
    )

    identities = list(adapter.iter_identities())

    assert [str(item.identity_key) for item in identities] == [
        "discord:user:3",
        "discord:user:4",
    ]
    assert fetch_limits == [None]


def test_iter_identities_rejects_missing_member_cache_and_fetch_api() -> None:
    guild = FakeGuild()
    guild.members = None
    guild.fetch_members = None

    adapter = DiscordSourceAdapter(
        FakeClient(guild),
        [123],
    )

    with pytest.raises(Exception) as exc_info:
        list(adapter.iter_identities())

    assert isinstance(exc_info.value, AdapterError)


def test_iter_identity_batches_bootstrap_from_members_without_history_scan() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    guild = FakeGuild()
    guild.members = [
        FakeMember(FakeUser(101, "User1"), "User1"),
        FakeMember(FakeUser(102, "User2"), "User2"),
        FakeMember(FakeUser(103, "User3"), "User3"),
    ]
    channel = MessageChannel(10, "history", 1, created)
    channel._messages = tuple(
        FakeMessage(
            index,
            channel,
            FakeUser(100 + index, f"User{index}"),
            created + timedelta(seconds=index),
            f"message-{index}",
        )
        for index in range(1, 4)
    )
    guild.channels = [channel]
    guild.threads = []

    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    batches = list(adapter.iter_identity_batches(batch_size=1))

    assert [str(identity.identity_key) for batch in batches for identity in batch.identities] == [
        "discord:user:101",
        "discord:user:102",
        "discord:user:103",
    ]
    assert batches[-1].complete is True
    assert channel.history_calls == 0
    assert adapter._message_cache == {}

    resumed = list(
        adapter.iter_identity_batches(
            batch_size=1,
            resume_cursor=batches[1].cursor,
        )
    )
    assert [str(identity.identity_key) for batch in resumed for identity in batch.identities] == [
        "discord:user:103",
    ]
    assert channel.history_calls == 0


def test_iter_conversations_maps_channels_and_threads() -> None:
    adapter = DiscordSourceAdapter(
        FakeClient(FakeGuild()),
        [123],
    )

    conversations = list(adapter.iter_conversations())

    assert [str(item.id) for item in conversations] == [
        "discord:guild:123:channel:10",
        "discord:guild:123:channel:20",
        "discord:guild:123:channel:30",
    ]
    assert conversations[0].conversation_type is ConversationType.CHANNEL
    assert conversations[2].conversation_type is ConversationType.THREAD
    assert conversations[2].parent_id == (
        "discord:guild:123:channel:20"
    )




def test_iter_conversations_includes_active_guild_threads_without_duplicates() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    guild = FakeGuild()
    guild.channels = [
        FakeChannel(10, "first", 1, created),
    ]
    guild.threads = [
        FakeThread(30, "thread", 10, 30, created),
        FakeThread(30, "thread-duplicate", 10, 31, created),
    ]

    adapter = DiscordSourceAdapter(
        FakeClient(guild),
        [123],
    )

    conversations = list(adapter.iter_conversations())

    assert [str(item.id) for item in conversations] == [
        "discord:guild:123:channel:10",
        "discord:guild:123:channel:30",
    ]
    assert conversations[1].conversation_type is ConversationType.THREAD
    assert conversations[1].parent_id == (
        "discord:guild:123:channel:10"
    )


def test_iter_conversations_includes_archived_public_and_private_threads() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    guild = FakeGuild()
    parent = FakeChannel(10, "first", 1, created)
    public_thread = FakeThread(40, "archived-public", 10, 40, created)
    private_thread = FakeThread(50, "archived-private", 10, 50, created)
    duplicate_thread = FakeThread(40, "duplicate", 10, 41, created)
    parent._archived_threads = {
        False: (public_thread, duplicate_thread),
        True: (private_thread,),
    }
    guild.channels = [parent]
    guild.threads = []

    adapter = DiscordSourceAdapter(
        FakeClient(guild),
        [123],
    )

    conversations = list(adapter.iter_conversations())

    assert [str(item.id) for item in conversations] == [
        "discord:guild:123:channel:10",
        "discord:guild:123:channel:40",
        "discord:guild:123:channel:50",
    ]
    assert conversations[1].conversation_type is ConversationType.THREAD
    assert conversations[2].conversation_type is ConversationType.THREAD
    assert conversations[1].parent_id == conversations[0].id
    assert conversations[2].parent_id == conversations[0].id


def test_source_adapter_rejects_sync_calls_inside_running_event_loop() -> None:
    async def run() -> None:
        adapter = DiscordSourceAdapter(
            FakeClient(FakeGuild()),
            [123],
        )

        unknown = DiscordSourceAdapter(
            FakeClient(FakeGuild()),
            [999],
        )
        with pytest.raises(AdapterError):
            list(unknown.iter_identities())

    import asyncio
    asyncio.run(run())


class FakeAttachment:
    def __init__(
        self,
        attachment_id: int,
        filename: str,
        data: bytes,
        content_type: str = "text/plain",
    ) -> None:
        self.id = attachment_id
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self) -> bytes:
        return self._data


class FakeReaction:
    def __init__(self, emoji, users) -> None:
        self.emoji = emoji
        self._users = users

    async def _users_iter(self, limit=None):
        for user in self._users:
            yield user

    def users(self, limit=None):
        return self._users_iter(limit=limit)


class FakeEmoji:
    def __init__(self, emoji_id: int, name: str) -> None:
        self.id = emoji_id
        self.name = name


class FakeReference:
    def __init__(
        self,
        message_id: int | None,
        resolved=None,
    ) -> None:
        self.message_id = message_id
        self.resolved = resolved


class FakeMessage:
    def __init__(
        self,
        message_id: int,
        channel: FakeChannel,
        author: FakeUser,
        created_at: datetime,
        content: str,
        *,
        system_content: str = "",
        edited_at: datetime | None = None,
        reference: FakeReference | None = None,
        attachments=(),
        reactions=(),
    ) -> None:
        self.id = message_id
        self.channel = channel
        self.author = author
        self.created_at = created_at
        self.edited_at = edited_at
        self.content = content
        self.system_content = system_content
        self.reference = reference
        self.attachments = attachments
        self.reactions = reactions
        self.embeds = []
        self.stickers = []
        self.components = []
        self.message_snapshots = []
        self.poll = None
        self.call = None
        self.activity = None
        self.purchase_notification = None


class MessageChannel(FakeChannel):
    def __init__(self, *args, messages=(), pinned=(), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._messages = tuple(messages)
        self._pinned = tuple(pinned)
        self.history_calls = 0

    def history(self, *, limit=None, oldest_first=True):
        self.history_calls += 1

        async def iterator():
            messages = self._messages if oldest_first else tuple(reversed(self._messages))
            for message in messages:
                yield message

        return iterator()

    async def pins(self, *, limit=None):
        return list(self._pinned)


def test_iter_pinned_message_ids_reads_current_channel_pin_set() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(10, "general", 1, created)
    message = FakeMessage(100, channel, user, created, "hello")
    channel._pinned = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())

    assert list(adapter.iter_pinned_message_ids(conversation)) == [
        "discord:message:100",
    ]


def test_thread_message_pin_is_canonicalized_with_thread_conversation() -> None:
    """A pin inside a Discord thread stays attached to that thread message."""
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    parent = FakeChannel(20, "general", 1, created)
    thread = MessageChannel(30, "discussion", 2, created)
    thread.type = SimpleNamespace(name="public_thread")
    thread.parent_id = parent.id
    message = FakeMessage(300, thread, user, created, "thread pin")
    thread._messages = (message,)
    thread._pinned = (message,)

    guild = FakeGuild()
    guild.channels = [parent, thread]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    conversations = list(adapter.iter_conversations())
    thread_conversation = next(
        conversation
        for conversation in conversations
        if conversation.conversation_type is ConversationType.THREAD
    )

    assert str(thread_conversation.id) == "discord:guild:123:channel:30"
    assert thread_conversation.parent_id == "discord:guild:123:channel:20"
    assert list(adapter.iter_pinned_message_ids(thread_conversation)) == [
        "discord:message:300",
    ]

    messages = list(adapter.iter_messages(thread_conversation))
    assert len(messages) == 1
    assert str(messages[0].conversation_id) == str(thread_conversation.id)
    assert messages[0].pinned is True


def test_iter_messages_streams_history_before_fetching_the_next_message() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(10, "general", 1, created)
    channel._messages = tuple(
        FakeMessage(
            index,
            channel,
            user,
            created + timedelta(seconds=index),
            f"message-{index}",
        )
        for index in range(1, 4)
    )
    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())

    messages = adapter.iter_messages(conversation)
    first = next(messages)

    assert str(first.id) == "discord:message:1"
    assert len(adapter._message_cache[str(conversation.id)]) == 1

    second = next(messages)
    assert str(second.id) == "discord:message:2"
    assert len(adapter._message_cache[str(conversation.id)]) == 2

    third = next(messages)
    assert str(third.id) == "discord:message:3"
    assert len(adapter._message_cache[str(conversation.id)]) == 3



def test_iter_messages_does_not_reuse_incremental_refresh_cache() -> None:
    """A complete traversal must never be truncated to the incremental window."""
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(10, "general", 1, created)
    old_message = FakeMessage(100, channel, user, created, "old")
    recent_message = FakeMessage(101, channel, user, created, "recent")
    channel._messages = (old_message, recent_message)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())

    # Model the cache populated by an incremental identity refresh.  This
    # contains only the bounded recent window and must not affect the full
    # source traversal used for deletion reconciliation.
    adapter._incremental_message_cache[str(conversation.id)] = (recent_message,)

    messages = list(adapter.iter_messages(conversation))

    assert [str(message.id) for message in messages] == [
        "discord:message:100",
        "discord:message:101",
    ]
    assert channel.history_calls == 1


def test_iter_messages_preserves_metadata_only_embed_message() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(10, "gallery-groups", 1, created)
    message = FakeMessage(200, channel, user, created, "")
    # This models a real-world embed whose useful Discord representation is
    # not covered by the currently extracted title/description/URL fields.
    message.embeds = [object()]
    message.stickers = []
    message.type = SimpleNamespace(name="default")
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())

    canonical = next(adapter.iter_messages(conversation))

    assert canonical.content == "[Discord embed message]"


def test_iter_messages_reports_truly_unrepresentable_empty_message_with_source_context() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(10, "gallery-groups", 1, created)
    message = FakeMessage(203, channel, user, created, "")
    message.type = SimpleNamespace(name="default")
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())

    with pytest.raises(
        AdapterError,
        match=(
            r".*Discord message discord:message:203.*"
            r"content_length=0; attachments=0; embeds=0; stickers=0; "
            r"components=0; message_snapshots=0; message_type=default"
        ),
    ):
        list(adapter.iter_messages(conversation))


def test_iter_messages_debug_diagnostic_includes_raw_discord_source_details(monkeypatch: pytest.MonkeyPatch) -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(12, "debug", 1, created)
    message = FakeMessage(202, channel, user, created, "")
    message.type = SimpleNamespace(name="default")
    message.flags = SimpleNamespace(value=123)
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())

    monkeypatch.setenv("ARCHIVE_SYNC_ENGINE_DISCORD_DEBUG_MESSAGES", "1")

    with pytest.raises(
        AdapterError,
        match=(
            r".*source_class=FakeMessage.*"
            r"source_module=.*test_source.*"
            r"content_repr='';.*"
            r"flags_repr=namespace\(value=123\).*"
            r"source_flags=namespace\(value=123\).*"
        ),
    ):
        list(adapter.iter_messages(conversation))


def test_iter_messages_preserves_role_subscription_message_as_content() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(14, "system-events", 1, created)
    message = FakeMessage(205, channel, user, created, "")
    message.role_subscription_data = SimpleNamespace(role_id=77)
    message.type = SimpleNamespace(name="default")
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())

    canonical = next(adapter.iter_messages(conversation))

    assert canonical.content == "[Discord role subscription message]"


def test_iter_messages_preserves_interaction_metadata_as_content() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(13, "interaction", 1, created)
    message = FakeMessage(204, channel, user, created, "")
    message.interaction_metadata = SimpleNamespace(id=999)
    message.type = SimpleNamespace(name="default")
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())

    canonical = next(adapter.iter_messages(conversation))

    assert canonical.content == "[Discord interaction message]"


def test_iter_messages_represents_empty_non_default_discord_system_message() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(11, "system-events", 1, created)
    message = FakeMessage(201, channel, user, created, "")
    message.embeds = []
    message.stickers = []
    message.components = []
    message.type = SimpleNamespace(name="recipient_remove")
    message.system_content = ""
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())

    messages = list(adapter.iter_messages(conversation))

    assert len(messages) == 1
    assert messages[0].content == "[Discord system message: recipient_remove]"


def test_iter_messages_maps_content_reply_attachment_reaction_and_pin_state() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(
        10,
        "first",
        1,
        created,
    )
    attachment = FakeAttachment(
        50,
        "document.txt",
        b"hello attachment",
    )
    reaction = FakeReaction(
        FakeEmoji(99, "custom-heart"),
        [user],
    )
    message = FakeMessage(
        100,
        channel,
        user,
        created,
        "hello",
        reference=FakeReference(90),
        attachments=(attachment,),
        reactions=(reaction,),
    )
    channel._messages = (message,)
    channel._pinned = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    adapter = DiscordSourceAdapter(
        FakeClient(guild),
        [123],
    )

    conversation = next(
        item
        for item in adapter.iter_conversations()
        if str(item.id).endswith("channel:10")
    )

    messages = list(adapter.iter_messages(conversation))

    assert len(messages) == 1
    canonical = messages[0]
    assert canonical.id == "discord:message:100"
    assert canonical.conversation_id == conversation.id
    assert canonical.identity_key == "discord:user:1"
    assert canonical.content == "hello"
    assert canonical.reply_to == "discord:message:90"
    assert canonical.pinned is True
    assert canonical.attachments[0].filename == "document.txt"
    assert canonical.attachments[0].size == len(b"hello attachment")
    assert canonical.attachments[0].sha256 == hashlib.sha256(
        b"hello attachment",
    ).hexdigest()
    assert canonical.reactions[0].identity_key == "discord:user:1"
    assert canonical.reactions[0].emoji_id == "99"
    assert canonical.reactions[0].is_custom is True

    assert adapter.attachment_bytes(canonical.attachments[0]) == b"hello attachment"


def test_iter_messages_preserves_unresolved_reply_reference() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(
        10,
        "first",
        1,
        created,
    )
    message = FakeMessage(
        100,
        channel,
        user,
        created,
        "reply whose target is unavailable",
        reference=FakeReference(90, resolved=None),
    )
    channel._messages = (message,)

    adapter = DiscordSourceAdapter(
        FakeClient(FakeGuild()),
        [123],
    )
    adapter._conversation_channels[
        "discord:guild:123:channel:10"
    ] = channel

    conversation = next(
        item
        for item in adapter.iter_conversations()
        if str(item.id).endswith("channel:10")
    )

    canonical = list(adapter.iter_messages(conversation))[0]

    assert canonical.reply_to == "discord:message:90"


def test_iter_messages_preserves_chronological_order() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(
        10,
        "first",
        1,
        created,
    )
    messages = (
        FakeMessage(100, channel, user, created, "first"),
        FakeMessage(
            101,
            channel,
            user,
            created.replace(second=1),
            "second",
        ),
    )
    channel._messages = messages

    guild = FakeGuild()
    guild.channels = [channel]
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())

    result = list(adapter.iter_messages(conversation))

    assert [str(message.id) for message in result] == [
        "discord:message:100",
        "discord:message:101",
    ]

def test_attachment_bytes_returns_cached_content() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(
        10,
        "first",
        1,
        created,
    )
    attachment = FakeAttachment(
        50,
        "document.txt",
        b"hello attachment",
    )
    message = FakeMessage(
        100,
        channel,
        user,
        created,
        "hello",
        attachments=(attachment,),
    )
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())
    canonical = next(adapter.iter_messages(conversation))

    assert adapter.attachment_bytes(canonical.attachments[0]) == (
        b"hello attachment"
    )


def test_attachment_bytes_raises_for_unknown_attachment() -> None:
    adapter = DiscordSourceAdapter(
        FakeClient(FakeGuild()),
        [123],
    )
    content = b"never downloaded"
    attachment = CanonicalAttachment(
        id=AttachmentId("attachment-unknown"),
        filename="unknown.txt",
        content_type="text/plain",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )

    with pytest.raises(NotFoundError, match="attachment-unknown"):
        adapter.attachment_bytes(attachment)



class PaginatedPinsChannel(MessageChannel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requested_pin_limit = None

    def pins(self, *, limit=50, before=None, oldest_first=False):
        self.requested_pin_limit = limit

        async def iterator():
            for message in self._pinned:
                yield message

        return iterator()


def test_iter_messages_collects_all_pins_from_paginated_discord_api() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = PaginatedPinsChannel(
        10,
        "first",
        1,
        created,
    )
    messages = tuple(
        FakeMessage(
            100 + index,
            channel,
            user,
            created + timedelta(seconds=index),
            f"message-{index}",
        )
        for index in range(75)
    )
    channel._messages = messages
    channel._pinned = messages

    guild = FakeGuild()
    guild.channels = [channel]
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())

    result = list(adapter.iter_messages(conversation))

    assert len(result) == 75
    assert all(message.pinned for message in result)
    assert channel.requested_pin_limit is None


def test_iter_identities_includes_historical_message_authors_and_reactors() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    guild = FakeGuild()
    author = FakeUser(99, "HistoricalAuthor")
    reactor = FakeUser(100, "HistoricalReactor")
    channel = MessageChannel(
        10,
        "history",
        1,
        created,
        messages=(
            FakeMessage(
                1,
                None,
                author,
                created,
                "historical",
                reactions=(
                    FakeReaction("👍", (reactor,)),
                ),
            ),
        ),
    )
    channel._messages[0].channel = channel
    guild.channels = [channel]
    guild.threads = []

    adapter = DiscordSourceAdapter(
        FakeClient(guild),
        [123],
    )

    identities = list(adapter.iter_identities())

    assert [str(identity.identity_key) for identity in identities] == [
        "discord:user:1",
        "discord:user:100",
        "discord:user:2",
        "discord:user:99",
    ]


def test_iter_identities_reuses_historical_message_scan_for_message_import() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(99, "HistoricalAuthor")
    channel = MessageChannel(10, "history", 1, created)
    message = FakeMessage(1, channel, user, created, "historical")
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []

    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    identities = list(adapter.iter_identities())
    conversation = next(adapter.iter_conversations())
    messages = list(adapter.iter_messages(conversation))

    assert "discord:user:99" in {str(item.identity_key) for item in identities}
    assert len(messages) == 1
    assert channel.history_calls == 1


def test_iter_identities_reports_progress_while_scanning_history() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(99, "HistoricalAuthor")
    channel = MessageChannel(10, "history", 1, created)
    channel._messages = tuple(
        FakeMessage(index, channel, user, created + timedelta(seconds=index), f"m-{index}")
        for index in range(1, 4)
    )
    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    events: list[tuple[int, str]] = []
    adapter.set_identity_scan_progress_callback(
        lambda current, detail: events.append((current, detail))
    )

    identities = list(adapter.iter_identities())

    assert "discord:user:99" in {str(identity.identity_key) for identity in identities}
    assert any(current == 0 and "Loading members" in detail for current, detail in events)
    assert any(current == 0 and "Scanning #history" in detail for current, detail in events)
    assert [current for current, _ in events if current > 0] == [1, 2, 3]


def test_iter_identities_reports_progress_during_reaction_user_pagination() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    guild = FakeGuild()
    channel = MessageChannel(10, "reaction-heavy", 1, created)
    author = FakeUser(999, "Author")
    reactors = [FakeUser(1000 + index, f"Reactor{index}") for index in range(105)]
    message = FakeMessage(
        1,
        channel,
        author,
        created,
        "many reactions",
        reactions=(FakeReaction("👍", reactors),),
    )
    channel._messages = (message,)
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    events: list[tuple[int, str]] = []
    adapter.set_identity_scan_progress_callback(
        lambda current, detail: events.append((current, detail))
    )

    identities = list(adapter.iter_identities())
    identity_keys = {str(identity.identity_key) for identity in identities}
    details = [detail for _, detail in events]

    assert "discord:user:999" in identity_keys
    assert all(f"discord:user:{1000 + index}" in identity_keys for index in range(105))
    assert any("Resolving reaction users in #reaction-heavy" in detail for detail in details)
    assert any("Resolved 100 reaction users" in detail for detail in details)
    assert any("Finished reaction identity discovery" in detail for detail in details)


def test_iter_conversations_fetches_channels_when_guild_cache_is_empty() -> None:
    guild = FakeGuild()
    guild.channels = []
    guild.threads = []
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fetched_channels = [FakeChannel(40, "fetched", 1, created)]
    fetch_calls: list[tuple[()]] = []

    async def fetch_channels():
        fetch_calls.append(())
        return fetched_channels

    guild.fetch_channels = fetch_channels

    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    conversations = list(adapter.iter_conversations())

    assert [str(item.id) for item in conversations] == [
        "discord:guild:123:channel:40",
    ]
    assert fetch_calls == [()]


def test_iter_conversations_fetches_active_threads_when_thread_cache_is_empty() -> None:
    guild = FakeGuild()
    guild.threads = []
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    thread = FakeThread(50, "active", 20, 50, created)
    fetch_calls: list[tuple[()]] = []

    class ActiveThreads:
        threads = [thread]

    async def fetch_active_threads():
        fetch_calls.append(())
        return ActiveThreads()

    guild.fetch_active_threads = fetch_active_threads

    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    conversations = list(adapter.iter_conversations())

    assert "discord:guild:123:channel:50" in {str(item.id) for item in conversations}
    assert fetch_calls == [()]


def test_iter_messages_uses_discord_system_content_for_system_messages() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(10, "first", 1, created)
    message = FakeMessage(100, channel, user, created, "", system_content="Alice pinned a message.")
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    conversation = next(adapter.iter_conversations())
    messages = list(adapter.iter_messages(conversation))

    assert len(messages) == 1
    assert messages[0].content == "Alice pinned a message."


def test_iter_messages_derives_empty_pins_add_system_message() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(10, "first", 1, created)
    message = FakeMessage(102, channel, user, created, "")
    message.system_content = ""
    message.type = SimpleNamespace(name="pins_add")
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    conversation = next(adapter.iter_conversations())
    messages = list(adapter.iter_messages(conversation))

    assert len(messages) == 1
    assert messages[0].content == "Alice pinned a message."


def test_iter_messages_canonicalizes_forwarded_message_snapshot_content() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(10, "gallery-groups", 1, created)
    message = FakeMessage(103, channel, user, created, "")
    message.message_snapshots = [
        SimpleNamespace(
            content="Forwarded gallery message.",
            embeds=[],
            stickers=[],
            components=[],
            attachments=[],
        ),
    ]
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    conversation = next(adapter.iter_conversations())
    canonical = next(adapter.iter_messages(conversation))

    assert canonical.content == "Forwarded gallery message."


def test_iter_messages_imports_forwarded_message_snapshot_attachments() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(10, "gallery-groups", 1, created)
    snapshot_attachment = FakeAttachment(900, "forwarded.png", b"snapshot-bytes")
    message = FakeMessage(104, channel, user, created, "")
    message.message_snapshots = [
        SimpleNamespace(
            content="",
            embeds=[],
            stickers=[],
            components=[],
            attachments=[snapshot_attachment],
        ),
    ]
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    conversation = next(adapter.iter_conversations())
    canonical = next(adapter.iter_messages(conversation))

    assert [attachment.filename for attachment in canonical.attachments] == [
        "forwarded.png",
    ]
    assert adapter.attachment_bytes(canonical.attachments[0]) == b"snapshot-bytes"


def test_iter_messages_canonicalizes_embed_only_message_content() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(10, "gallery-groups", 1, created)
    message = FakeMessage(102, channel, user, created, "")
    message.embeds = [
        SimpleNamespace(
            title="Gallery update",
            description="A description from the embed.",
            url="https://example.test/gallery",
            author=SimpleNamespace(name="Gallery Bot", url=""),
            fields=(SimpleNamespace(name="Status", value="Ready"),),
            footer=SimpleNamespace(text="Source footer"),
            image=SimpleNamespace(url="https://example.test/image.png"),
            thumbnail=SimpleNamespace(url=""),
        ),
    ]
    message.stickers = []
    message.components = []
    message.type = SimpleNamespace(name="default")
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    conversation = next(adapter.iter_conversations())
    canonical = next(adapter.iter_messages(conversation))

    assert canonical.content == (
        "Gallery update\n"
        "A description from the embed.\n"
        "https://example.test/gallery\n"
        "Gallery Bot\n"
        "Status\n"
        "Ready\n"
        "Source footer\n"
        "https://example.test/image.png"
    )


def test_iter_messages_canonicalizes_poll_message_content() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(10, "gallery-groups", 1, created)
    message = FakeMessage(104, channel, user, created, "")
    message.poll = SimpleNamespace(
        question=SimpleNamespace(text="Which gallery should we use?"),
        answers=(
            SimpleNamespace(text="Gallery A"),
            SimpleNamespace(text="Gallery B"),
        ),
    )
    message.type = SimpleNamespace(name="default")
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    conversation = next(adapter.iter_conversations())
    canonical = next(adapter.iter_messages(conversation))

    assert canonical.content == (
        "Poll: Which gallery should we use?\n"
        "- Gallery A\n"
        "- Gallery B"
    )


def test_iter_messages_preserves_empty_discord_message_with_special_content_feature() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(10, "gallery-groups", 1, created)
    message = FakeMessage(105, channel, user, created, "")
    message.activity = SimpleNamespace(name="Watch Together")
    message.type = SimpleNamespace(name="default")
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    conversation = next(adapter.iter_conversations())
    canonical = next(adapter.iter_messages(conversation))

    assert canonical.content == "[Discord activity message]"


def test_iter_messages_rejects_unrepresentable_empty_discord_message() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")
    channel = MessageChannel(10, "first", 1, created)
    message = FakeMessage(101, channel, user, created, "")
    channel._messages = (message,)

    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    conversation = next(adapter.iter_conversations())
    with pytest.raises(AdapterError, match="A message must contain text or at least one attachment"):
        list(adapter.iter_messages(conversation))


def test_iter_messages_since_uses_bounded_discord_history_window() -> None:
    from archive_sync_engine.adapters.source import SourceRefreshCursor

    created = datetime(2026, 8, 18, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")

    class IncrementalChannel(FakeChannel):
        def __init__(self):
            super().__init__(10, "first", 1, created)
            self.history_after = None
            self._messages = (
                FakeMessage(100, self, user, created, "new"),
            )

        def history(self, *, limit=None, oldest_first=True, after=None):
            self.history_after = after

            async def iterator():
                for message in self._messages:
                    yield message

            return iterator()

    channel = IncrementalChannel()
    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []

    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())
    cursor = SourceRefreshCursor(
        created_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
        message_id="99",
    )

    messages = list(adapter.iter_messages_since(conversation, cursor))

    assert [str(message.id) for message in messages] == [
        "discord:message:100",
    ]
    assert channel.history_after == datetime(2026, 8, 10, tzinfo=timezone.utc)
    assert adapter.incremental_refresh_lookback == timedelta(days=7)



def test_iter_custom_emojis_fetches_authoritative_guild_emoji_list() -> None:
    content = b"fetched-mewheart"

    class FakeEmoji:
        id = 1513447466333110352
        name = "mewheart"
        animated = False
        url = SimpleNamespace(read=lambda: _read())

    async def _read():
        return content

    class FetchingGuild(FakeGuild):
        def __init__(self) -> None:
            super().__init__()
            self.emojis = []
            self.fetch_emojis_calls = 0

        async def fetch_emojis(self):
            self.fetch_emojis_calls += 1
            return [FakeEmoji()]

    guild = FetchingGuild()
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    emojis = list(adapter.iter_custom_emojis())

    assert [str(emoji.id) for emoji in emojis] == ["1513447466333110352"]
    assert adapter.custom_emoji_bytes(emojis[0]) == content
    assert guild.fetch_emojis_calls == 1

def test_iter_custom_emojis_reads_real_discord_emoji_asset_api() -> None:
    content = b"discord-read-mewheart"

    async def _read():
        return content

    class RealApiEmoji:
        id = 1513447466333110352
        name = "mewheart"
        animated = False
        url = "https://cdn.discordapp.com/emojis/1513447466333110352.png"

        async def read(self):
            return await _read()

    guild = FakeGuild()
    guild.emojis = [RealApiEmoji()]
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    emojis = list(adapter.iter_custom_emojis())

    assert len(emojis) == 1
    assert str(emojis[0].id) == "1513447466333110352"
    assert adapter.custom_emoji_bytes(emojis[0]) == content


def test_iter_custom_emojis_archives_source_asset_bytes() -> None:
    content = b"mewheart-png"

    class FakeEmoji:
        id = 1513447466333110352
        name = "mewheart"
        animated = False
        url = SimpleNamespace(read=lambda: _read())

    async def _read():
        return content

    guild = FakeGuild()
    guild.emojis = [FakeEmoji()]
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])

    emojis = list(adapter.iter_custom_emojis())

    assert len(emojis) == 1
    assert str(emojis[0].id) == "1513447466333110352"
    assert emojis[0].name == "mewheart"
    assert emojis[0].size == len(content)
    assert emojis[0].sha256 == hashlib.sha256(content).hexdigest()
    assert adapter.custom_emoji_bytes(emojis[0]) == content


def test_iter_custom_emojis_archives_reaction_emoji_from_another_guild() -> None:
    content = b"reaction-only-mewheart"

    async def _read():
        return content

    emoji = SimpleNamespace(
        id=1513447466333110352,
        name="mewheart",
        animated=False,
        url=SimpleNamespace(read=lambda: _read()),
    )
    message = SimpleNamespace(
        reactions=[SimpleNamespace(emoji=emoji)],
    )

    guild = FakeGuild()
    guild.emojis = []
    guild.fetch_emojis = None
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    adapter._message_cache["discord:conversation:123"] = (message,)

    emojis = list(adapter.iter_custom_emojis())

    assert [str(item.id) for item in emojis] == ["1513447466333110352"]
    assert emojis[0].name == "mewheart"
    assert adapter.custom_emoji_bytes(emojis[0]) == content



def test_unknown_discord_guild_becomes_actionable_adapter_error() -> None:
    class UnknownGuildError(Exception):
        status = 404
        code = 10004

    class MissingGuildClient(FakeClient):
        async def fetch_guild(self, guild_id: int):
            raise UnknownGuildError("Unknown Guild")

    adapter = DiscordSourceAdapter(MissingGuildClient(FakeGuild()), [590473181571579900])

    with pytest.raises(NotFoundError) as error:
        list(adapter._iter_guilds())

    message = str(error.value)
    assert "590473181571579900" in message
    assert "discord.guild_id" in message
    assert "member of that server" in message


def test_unrelated_discord_fetch_error_is_not_rewritten() -> None:
    class ForbiddenError(Exception):
        status = 403
        code = 50001

    class ForbiddenGuildClient(FakeClient):
        async def fetch_guild(self, guild_id: int):
            raise ForbiddenError("Missing Access")

    adapter = DiscordSourceAdapter(ForbiddenGuildClient(FakeGuild()), [999])

    with pytest.raises(ForbiddenError, match="Missing Access"):
        list(adapter._iter_guilds())


def test_iter_messages_after_checkpoint_uses_native_discord_history_boundary() -> None:
    from archive_sync_engine.adapters.source import SourceRefreshCursor

    created = datetime(2026, 8, 18, tzinfo=timezone.utc)
    user = FakeUser(1, "Alice")

    class ResumeChannel(FakeChannel):
        def __init__(self):
            super().__init__(10, "first", 1, created)
            self.history_after = None
            self._messages = (
                FakeMessage(100, self, user, created, "first"),
                FakeMessage(101, self, user, created + timedelta(minutes=1), "second"),
            )

        def history(self, *, limit=None, oldest_first=True, after=None):
            self.history_after = after

            async def iterator():
                for message in self._messages:
                    if after is None or message.created_at >= after:
                        yield message

            return iterator()

    channel = ResumeChannel()
    guild = FakeGuild()
    guild.channels = [channel]
    guild.threads = []
    adapter = DiscordSourceAdapter(FakeClient(guild), [123])
    conversation = next(adapter.iter_conversations())
    cursor = SourceRefreshCursor(created_at=created, message_id="discord:message:100")

    messages = list(adapter.iter_messages_after_checkpoint(conversation, cursor))

    assert [str(message.id) for message in messages] == ["discord:message:101"]
    assert channel.history_after == created - timedelta(microseconds=1)


def test_close_async_iterator_is_safe_after_runtime_event_loop_closes() -> None:
    import asyncio

    adapter = DiscordSourceAdapter(FakeClient(FakeGuild()), [123])
    loop = asyncio.new_event_loop()
    adapter.set_runner(loop.run_until_complete)

    closed = []

    async def close() -> None:
        closed.append(True)

    loop.close()

    adapter._close_async_iterator(close)

    assert closed == []
