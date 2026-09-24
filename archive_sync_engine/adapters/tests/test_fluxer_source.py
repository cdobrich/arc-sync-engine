from __future__ import annotations

from datetime import datetime, timezone

from archive_sync_engine.adapters.fluxer_source import FluxerSourceAdapter
from archive_sync_engine.models import ConversationType


class FakeFluxerSourceClient:
    def __init__(self) -> None:
        self.reaction_calls = []
        self.downloads = []

    async def get_guild_channels(self, guild_id: str):
        assert guild_id == "guild-1"
        return [
            {"id": "channel-1", "name": "general", "type": 0},
            {"id": "voice-1", "name": "voice", "type": 2},
        ]

    async def get_channel_messages(self, channel_id: str, *, before=None):
        assert channel_id == "channel-1"
        if before is None:
            return [
                {
                    "id": "message-1",
                    "author": {"id": "user-1", "username": "Alice"},
                    "content": "hello",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "pinned": True,
                    "attachments": [
                        {
                            "id": "attachment-1",
                            "filename": "hello.txt",
                            "content_type": "text/plain",
                            "size": 5,
                            "url": "https://files.example/hello.txt",
                        }
                    ],
                    "reactions": [
                        {"emoji": {"id": None, "name": "👍"}, "count": 1},
                    ],
                }
            ]
        return []

    async def get_reaction_users(self, channel_id: str, message_id: str, emoji: str):
        self.reaction_calls.append((channel_id, message_id, emoji))
        return [{"id": "user-2", "username": "Bob"}]

    async def get_guild_emojis(self, guild_id: str):
        return [
            {
                "id": "emoji-1",
                "name": "party_parrot",
                "animated": False,
                "url": "https://files.example/party.png",
            }
        ]

    async def download_url(self, url: str) -> bytes:
        self.downloads.append(url)
        return b"emoji" if url.endswith("party.png") else b"hello"


def test_fluxer_source_discovers_conversations_by_stable_channel_id() -> None:
    adapter = FluxerSourceAdapter(FakeFluxerSourceClient(), ("guild-1",))

    conversations = list(adapter.iter_conversations())

    assert len(conversations) == 1
    assert conversations[0].id == "fluxer:guild:guild-1:channel:channel-1"
    assert conversations[0].conversation_type is ConversationType.CHANNEL
    assert conversations[0].title == "general"


def test_fluxer_source_imports_messages_attachments_reactions_and_pins() -> None:
    client = FakeFluxerSourceClient()
    adapter = FluxerSourceAdapter(client, ("guild-1",))
    conversation = next(iter(adapter.iter_conversations()))

    identities = list(adapter.iter_identities())
    messages = list(adapter.iter_messages(conversation))

    assert {str(identity.identity_key) for identity in identities} == {
        "fluxer:user:user-1",
        "fluxer:user:user-2",
    }
    assert len(messages) == 1
    message = messages[0]
    assert message.id == "fluxer:message:message-1"
    assert message.identity_key == "fluxer:user:user-1"
    assert message.pinned is True
    assert message.attachments[0].filename == "hello.txt"
    assert message.attachments[0].sha256 == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )
    assert message.reactions[0].identity_key == "fluxer:user:user-2"
    assert message.reactions[0].emoji == "👍"
    assert client.reaction_calls == [("channel-1", "message-1", "👍")]


def test_fluxer_source_preserves_system_message_events() -> None:
    class Client(FakeFluxerSourceClient):
        async def get_channel_messages(self, channel_id: str, *, before=None):
            if before is not None:
                return []
            return [
                {
                    "id": "message-2",
                    "author": {"id": "user-1", "username": "Alice"},
                    "content": "",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "type": 6,
                    "attachments": [],
                    "reactions": [],
                }
            ]

    adapter = FluxerSourceAdapter(Client(), ("guild-1",))
    conversation = next(iter(adapter.iter_conversations()))
    message = next(iter(adapter.iter_messages(conversation)))

    assert message.content == "Alice pinned a message to this channel."



def test_fluxer_source_custom_emoji_accepts_image_url_alias() -> None:
    class Client(FakeFluxerSourceClient):
        async def get_guild_emojis(self, guild_id: str):
            return [{
                "id": "emoji-image",
                "name": "image_alias",
                "animated": False,
                "image_url": "https://example.invalid/emojis/emoji-image.png",
            }]

        async def download_url(self, url: str) -> bytes:
            assert url == "https://example.invalid/emojis/emoji-image.png"
            return b"image"

    adapter = FluxerSourceAdapter(Client(), ("guild-1",))
    emoji = next(iter(adapter.iter_custom_emojis()))

    assert emoji.name == "image_alias"
    assert adapter.custom_emoji_bytes(emoji) == b"image"


def test_fluxer_source_custom_emoji_reads_bytes_from_runtime_supplied_url() -> None:
    class Client(FakeFluxerSourceClient):
        async def get_guild_emojis(self, guild_id: str):
            return [
                {
                    "id": "emoji-2",
                    "name": "runtime_supplied",
                    "animated": False,
                    "url": "https://fluxerstatic.com/emojis/emoji-2.png",
                }
            ]

    client = Client()
    adapter = FluxerSourceAdapter(client, ("guild-1",))

    emoji = next(iter(adapter.iter_custom_emojis()))

    assert emoji.id == "emoji-2"
    assert adapter.custom_emoji_bytes(emoji) == b"hello"
    assert client.downloads == ["https://fluxerstatic.com/emojis/emoji-2.png"]


def test_fluxer_source_custom_emoji_assets_are_content_addressed() -> None:
    client = FakeFluxerSourceClient()
    adapter = FluxerSourceAdapter(client, ("guild-1",))

    emoji = next(iter(adapter.iter_custom_emojis()))

    assert emoji.id == "emoji-1"
    assert emoji.name == "party_parrot"
    assert emoji.sha256 == "4030f0c0b99ba5e189b6fe295448a8ca31ca589a55930175de18032545c11501"
    assert adapter.custom_emoji_bytes(emoji) == b"emoji"


def test_fluxer_source_custom_emoji_retries_extensionless_asset_after_404() -> None:
    from urllib.error import HTTPError

    class Client(FakeFluxerSourceClient):
        async def get_guild_emojis(self, guild_id: str):
            return [{
                "id": "emoji-fallback",
                "name": "fallback",
                "animated": False,
                "url": "https://example.invalid/emojis/emoji-fallback",
            }]

        async def download_url(self, url: str) -> bytes:
            if url.endswith("/emoji-fallback"):
                raise HTTPError(url, 404, "Not Found", None, None)
            if url.endswith("/emoji-fallback.png"):
                return b"fallback"
            raise AssertionError(url)

    adapter = FluxerSourceAdapter(Client(), ("guild-1",))
    emoji = next(iter(adapter.iter_custom_emojis()))

    assert adapter.custom_emoji_bytes(emoji) == b"fallback"


def test_fluxer_source_skips_custom_emoji_when_asset_bytes_are_unavailable(caplog) -> None:
    from urllib.error import HTTPError

    class Client:
        async def get_guild_channels(self, guild_id):
            return []

        async def get_channel_messages(self, channel_id, *, before=None):
            return []

        async def get_reaction_users(self, channel_id, message_id, emoji):
            return []

        async def get_guild_emojis(self, guild_id):
            return [{
                "id": "emoji-missing",
                "name": "missing",
                "url": "https://assets.example/emoji-missing.png",
            }]

        async def download_url(self, url):
            raise HTTPError(url, 404, "Not Found", None, None)

    adapter = FluxerSourceAdapter(Client(), ("guild-1",))

    with caplog.at_level("WARNING"):
        assert list(adapter.iter_custom_emojis()) == []

    assert "Skipping Fluxer custom emoji emoji-missing (missing)" in caplog.text


def test_fluxer_source_uses_pin_collection_when_message_history_omits_pinned_field() -> None:
    class Client(FakeFluxerSourceClient):
        async def get_channel_messages(self, channel_id: str, *, before=None):
            if before is not None:
                return []
            return [{
                "id": "message-1",
                "author": {"id": "user-1", "username": "Alice"},
                "content": "hello",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "attachments": [],
                "reactions": [],
            }]

        async def get_pinned_message_ids(self, channel_id: str):
            assert channel_id == "channel-1"
            return {"message-1"}

    adapter = FluxerSourceAdapter(Client(), ("guild-1",))
    conversation = next(iter(adapter.iter_conversations()))
    message = next(iter(adapter.iter_messages(conversation)))

    assert message.pinned is True
