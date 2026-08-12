from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from archive_sync_engine.adapters import DiscordSourceAdapter
from archive_sync_engine.adapters.exceptions import AdapterError
from archive_sync_engine.models import ConversationType


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


def test_iter_messages_is_explicitly_deferred_to_message_slice() -> None:
    adapter = DiscordSourceAdapter(
        FakeClient(FakeGuild()),
        [123],
    )

    conversation = next(adapter.iter_conversations())

    with pytest.raises(NotImplementedError):
        list(adapter.iter_messages(conversation))


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
