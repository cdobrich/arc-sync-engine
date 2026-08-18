from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from archive_sync_engine.adapters import DiscordSourceAdapter


class FakeUser:
    def __init__(self, user_id: int, name: str) -> None:
        self.id = user_id
        self.name = name
        self.global_name = None
        self.bot = False


class FakeChannel:
    def __init__(self, channel_id: int, created_at: datetime) -> None:
        self.id = channel_id
        self.name = "system-messages"
        self.position = 0
        self.created_at = created_at
        self.type = SimpleNamespace(name="text")
        self._messages = ()
        self._pinned = ()

    def history(self, *, limit=None, oldest_first=True):
        async def iterator():
            for message in self._messages:
                yield message

        return iterator()

    def pins(self, *, limit=None):
        async def iterator():
            for message in self._pinned:
                yield message

        return iterator()


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
    ) -> None:
        self.id = message_id
        self.channel = channel
        self.author = author
        self.created_at = created_at
        self.content = content
        self.system_content = system_content
        self.edited_at = None
        self.reference = None
        self.attachments = ()
        self.reactions = ()
        self.type = SimpleNamespace(name="pins_add")


class FakeGuild:
    def __init__(self, channel: FakeChannel) -> None:
        self.id = 123
        self.name = "test"
        self.channels = [channel]
        self.threads = []
        self.members = []

    def fetch_members(self, *, limit=None):
        async def iterator():
            if False:
                yield None

        return iterator()


class FakeClient:
    def __init__(self, guild: FakeGuild) -> None:
        self.guild = guild

    def get_guild(self, guild_id: int):
        return self.guild

    async def fetch_guild(self, guild_id: int):
        return self.guild


def test_system_message_uses_discord_system_content() -> None:
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    channel = FakeChannel(10, created)
    message = FakeMessage(
        100,
        channel,
        FakeUser(1, "Alice"),
        created,
        "",
        system_content="Alice pinned a message.",
    )
    channel._messages = (message,)

    adapter = DiscordSourceAdapter(FakeClient(FakeGuild(channel)), [123])
    conversation = next(adapter.iter_conversations())

    canonical = next(adapter.iter_messages(conversation))

    assert canonical.content == "Alice pinned a message."
