from __future__ import annotations

import hashlib
from datetime import datetime, timezone
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
    def __init__(self, message_id: int | None) -> None:
        self.message_id = message_id


class FakeMessage:
    def __init__(
        self,
        message_id: int,
        channel: FakeChannel,
        author: FakeUser,
        created_at: datetime,
        content: str,
        *,
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
        self.reference = reference
        self.attachments = attachments
        self.reactions = reactions


class MessageChannel(FakeChannel):
    def __init__(self, *args, messages=(), pinned=(), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._messages = tuple(messages)
        self._pinned = tuple(pinned)

    def history(self, *, limit=None, oldest_first=True):
        async def iterator():
            messages = self._messages if oldest_first else tuple(reversed(self._messages))
            for message in messages:
                yield message

        return iterator()

    async def pins(self):
        return list(self._pinned)


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

