from __future__ import annotations

import asyncio

from pathlib import Path
from types import SimpleNamespace

import pytest

from archive_sync_engine.adapters.exceptions import AdapterError
from archive_sync_engine.adapters.fluxer_source_runtime import (
    FluxerSourceRuntime,
    FluxerSourceRuntimeConfig,
    build_fluxer_source_runtime_config,
)
from archive_sync_engine.adapters.fluxer_runtime import FluxerHttpClientFactory
from archive_sync_engine.adapters.source_runtime_request import SourceRuntimeRequest


class _PinHTTP:
    def __init__(self, payload, *, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def _route(self, method, path, **params):
        return SimpleNamespace(method=method, path=path, params=params)

    async def request(self, route, **kwargs):
        self.calls.append((route.method, route.path, route.params, kwargs))
        if self.error is not None:
            error = self.error
            self.error = None
            raise error
        return self.payload


def test_build_fluxer_source_runtime_config_uses_override_token() -> None:
    config = build_fluxer_source_runtime_config(
        SimpleNamespace(fluxer_token="configured"),
        ("guild-1",),
        {"token": "override", "max_retries": 7},
    )

    assert config.token == "override"
    assert config.guild_ids == ("guild-1",)
    assert config.max_retries == 7


def test_fluxer_source_runtime_factory_rejects_wrong_adapter(tmp_path: Path) -> None:
    request = SourceRuntimeRequest(
        "discord",
        ("guild-1",),
        tmp_path,
        {},
    )

    with pytest.raises(AdapterError, match="requires the fluxer source adapter"):
        FluxerSourceRuntime.from_source_runtime_request(request)


def test_fluxer_source_runtime_owns_and_closes_http_client() -> None:
    created = []

    class FakeHTTP:
        def __init__(self, token: str, **kwargs) -> None:
            created.append((token, kwargs))
            self.closed = 0

        async def close(self) -> None:
            self.closed += 1

    factory = FluxerHttpClientFactory(
        importer=lambda: SimpleNamespace(HTTPClient=FakeHTTP),
    )
    runtime = FluxerSourceRuntime(
        FluxerSourceRuntimeConfig(token="token", guild_ids=("guild-1",)),
        factory=factory,
    )

    assert runtime.adapter.name == "Fluxer"
    assert runtime.input_scope == ("guild-1",)
    runtime.close()
    runtime.close()
    assert created == [("token", {"is_bot": True, "max_retries": 4, "retry_forever": False})]


def test_fluxer_source_client_synthesizes_official_emoji_asset_urls() -> None:
    import asyncio
    from archive_sync_engine.adapters.fluxer_source_runtime import FluxerHttpSourceClient

    class FakeHTTP:
        api_url = "https://api.fluxer.app/v1"

        async def get_guild_emojis(self, guild_id):
            assert guild_id == "guild-1"
            return [
                {"id": "emoji-1", "name": "party", "animated": False},
                {"id": "emoji-2", "name": "dance", "animated": True},
            ]

    emojis = asyncio.run(FluxerHttpSourceClient(FakeHTTP()).get_guild_emojis("guild-1"))

    assert emojis[0]["url"] == "https://fluxerstatic.com/emojis/emoji-1"
    assert emojis[1]["url"] == "https://fluxerstatic.com/emojis/emoji-2"


def test_fluxer_source_client_preserves_existing_emoji_urls() -> None:
    import asyncio
    from archive_sync_engine.adapters.fluxer_source_runtime import FluxerHttpSourceClient

    class FakeHTTP:
        api_url = "https://api.fluxer.app/v1"

        async def get_guild_emojis(self, guild_id):
            return [{"id": "emoji-1", "name": "party", "url": "https://custom/party.png"}]

    emojis = asyncio.run(FluxerHttpSourceClient(FakeHTTP()).get_guild_emojis("guild-1"))

    assert emojis[0]["url"] == "https://custom/party.png"



def test_fluxer_source_client_preserves_existing_emoji_image_url_alias() -> None:
    import asyncio
    from archive_sync_engine.adapters.fluxer_source_runtime import FluxerHttpSourceClient

    class FakeHTTP:
        api_url = "https://api.fluxer.app/v1"

        async def get_guild_emojis(self, guild_id):
            return [{
                "id": "emoji-image",
                "name": "image_alias",
                "animated": False,
                "image_url": "https://cdn.example/emojis/emoji-image.webp",
            }]

    emojis = asyncio.run(FluxerHttpSourceClient(FakeHTTP()).get_guild_emojis("guild-1"))

    assert emojis[0]["image_url"] == "https://cdn.example/emojis/emoji-image.webp"
    assert "url" not in emojis[0]


def test_fluxer_source_client_preserves_slotted_emoji_image_url_alias() -> None:
    import asyncio
    from archive_sync_engine.adapters.fluxer_source_runtime import FluxerHttpSourceClient

    class Emoji:
        __slots__ = ("id", "name", "animated", "image_url")

        def __init__(self):
            self.id = "emoji-image"
            self.name = "image_alias"
            self.animated = False
            self.image_url = "https://cdn.example/emojis/emoji-image.webp"

    class FakeHTTP:
        api_url = "https://api.fluxer.app/v1"

        async def get_guild_emojis(self, guild_id):
            return [Emoji()]

    emojis = asyncio.run(FluxerHttpSourceClient(FakeHTTP()).get_guild_emojis("guild-1"))

    assert emojis[0].image_url == "https://cdn.example/emojis/emoji-image.webp"

def test_fluxer_source_client_synthesizes_url_for_slotted_emoji_model() -> None:
    import asyncio
    from archive_sync_engine.adapters.fluxer_source_runtime import FluxerHttpSourceClient

    class Emoji:
        __slots__ = ("id", "name", "animated")

        def __init__(self):
            self.id = "emoji-1"
            self.name = "party"
            self.animated = False

    class FakeHTTP:
        api_url = "https://api.fluxer.app/v1"

        async def get_guild_emojis(self, guild_id):
            return [Emoji()]

    emojis = asyncio.run(FluxerHttpSourceClient(FakeHTTP()).get_guild_emojis("guild-1"))

    assert emojis == [
        {
            "id": "emoji-1",
            "name": "party",
            "animated": False,
            "url": "https://fluxerstatic.com/emojis/emoji-1",
        }
    ]


def test_fluxer_source_runtime_reads_pin_collection_when_history_omits_pin_flag() -> None:
    from archive_sync_engine.adapters.fluxer_source_runtime import FluxerHttpSourceClient

    http = _PinHTTP({"items": [{"message": {"id": "message-1"}}, {"message": {"id": "message-2"}}]})
    client = FluxerHttpSourceClient(http)

    assert asyncio.run(client.get_pinned_message_ids("channel-1")) == {"message-1", "message-2"}
    assert http.calls[0][1] == "/channels/{channel_id}/messages/pins"


def test_fluxer_source_runtime_falls_back_to_legacy_pin_collection_on_404() -> None:
    from archive_sync_engine.adapters.fluxer_source_runtime import FluxerHttpSourceClient

    class NotFound(Exception):
        code = 404

    http = _PinHTTP([{"id": "message-legacy"}], error=NotFound())
    client = FluxerHttpSourceClient(http)

    assert asyncio.run(client.get_pinned_message_ids("channel-1")) == {"message-legacy"}
    assert [call[1] for call in http.calls] == [
        "/channels/{channel_id}/messages/pins",
        "/channels/{channel_id}/pins",
    ]
