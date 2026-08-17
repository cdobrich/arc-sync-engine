from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from archive_sync_engine.adapters import DestinationConversationRef
from archive_sync_engine.adapters.exceptions import AdapterError
from archive_sync_engine.models import CanonicalConversation, CanonicalMessage
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.ids import ConversationId, IdentityKey, MessageId
from archive_sync_engine.adapters.fluxer import FluxerIdentityMapping
from archive_sync_engine.adapters.fluxer_runtime import (
    FluxerClientConfig,
    FluxerDestinationRuntime,
    FluxerHttpClientFactory,
    FluxerHttpDestinationClient,
)


class FakeHTTPClient:
    instances: list["FakeHTTPClient"] = []

    def __init__(self, token: str, **kwargs) -> None:
        self.token = token
        self.kwargs = kwargs
        self.closed = False
        self.created_channel_calls = []
        self.send_message_calls = []
        self.request_calls = []
        type(self).instances.append(self)

    async def close(self) -> None:
        self.closed = True

    async def create_guild_channel(self, guild_id, *, name, type):
        self.created_channel_calls.append((guild_id, name, type))
        return {"id": "channel-1"}

    async def send_message(self, channel_id, *, content=None, files=None, message_reference=None):
        self.send_message_calls.append(
            (channel_id, content, files, message_reference),
        )
        return {"id": "message-1", "channel_id": channel_id}

    async def edit_message(self, channel_id, message_id, *, content=None, embeds=None):
        return {"id": message_id, "channel_id": channel_id}

    async def delete_message(self, channel_id, message_id):
        return None

    async def delete_channel(self, channel_id):
        return None

    async def add_reaction(self, channel_id, message_id, emoji):
        return None

    async def delete_reaction(self, channel_id, message_id, emoji, user_id="@me"):
        return None

    async def pin_message(self, channel_id, message_id):
        return None

    async def unpin_message(self, channel_id, message_id):
        return None

    async def get_message(self, channel_id, message_id):
        return {
            "id": message_id,
            "channel_id": channel_id,
            "attachments": [
                {"id": "attachment-1", "filename": "keep.txt"},
                {"id": "attachment-2", "filename": "remove.txt"},
            ],
        }

    def _route(self, method, path, **params):
        from types import SimpleNamespace
        return SimpleNamespace(method=method, path=path, params=params)

    async def request(self, route, *, json=None, **kwargs):
        self.request_calls.append((route.method, route.path, json))
        return None


@pytest.fixture(autouse=True)
def reset_clients() -> None:
    FakeHTTPClient.instances.clear()


def _factory() -> FluxerHttpClientFactory:
    return FluxerHttpClientFactory(
        importer=lambda: SimpleNamespace(HTTPClient=FakeHTTPClient),
    )


def test_fluxer_runtime_constructs_bot_http_client() -> None:
    calls: list[tuple[str, dict]] = []

    class FakeRuntimeHTTPClient:
        def __init__(self, token: str, **kwargs) -> None:
            calls.append((token, kwargs))

    factory = FluxerHttpClientFactory(
        importer=lambda: SimpleNamespace(HTTPClient=FakeRuntimeHTTPClient),
    )

    client = factory.create(
        FluxerClientConfig(
            token="bot-token",
            is_bot=True,
            api_url="https://fluxer.example/v1",
            max_retries=7,
            retry_forever=True,
        )
    )

    assert isinstance(client, FakeRuntimeHTTPClient)
    assert calls == [
        (
            "bot-token",
            {
                "is_bot": True,
                "api_url": "https://fluxer.example/v1",
                "max_retries": 7,
                "retry_forever": True,
            },
        ),
    ]


def test_fluxer_runtime_constructs_user_http_client_without_gateway() -> None:
    calls: list[tuple[str, dict]] = []

    class FakeRuntimeHTTPClient:
        def __init__(self, token: str, **kwargs) -> None:
            calls.append((token, kwargs))

    class FakeGatewayClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("gateway Client must not be constructed")

    factory = FluxerHttpClientFactory(
        importer=lambda: SimpleNamespace(
            HTTPClient=FakeRuntimeHTTPClient,
            Client=FakeGatewayClient,
        ),
    )

    factory.create(
        FluxerClientConfig(
            token="user-token",
            is_bot=False,
        )
    )

    assert calls == [
        (
            "user-token",
            {
                "is_bot": False,
                "max_retries": 4,
                "retry_forever": False,
            },
        ),
    ]


def test_fluxer_runtime_reports_missing_dependency_as_adapter_error() -> None:
    factory = FluxerHttpClientFactory(
        importer=lambda: (_ for _ in ()).throw(ImportError("missing")),
    )

    with pytest.raises(AdapterError, match="fluxer.py dependency"):
        factory.create(
            FluxerClientConfig(
                token="bot-token",
            )
        )


def test_fluxer_runtime_rejects_empty_token() -> None:
    with pytest.raises(ValueError, match="token"):
        FluxerClientConfig(token="")


def test_runtime_wires_real_rest_clients_into_destination_adapter() -> None:
    runtime = FluxerDestinationRuntime(
        guild_id="guild-1",
        bot_client=FluxerClientConfig(token="bot-token"),
        client_factory=_factory(),
    )

    reference = runtime.adapter.create_conversation(
        CanonicalConversation(
            id=ConversationId("conversation-1"),
            conversation_type=ConversationType.CHANNEL,
            title="general",
        )
    )

    assert reference.id == "channel-1"
    assert FakeHTTPClient.instances[0].created_channel_calls == [
        ("guild-1", "general", 0),
    ]

    runtime.close()
    assert FakeHTTPClient.instances[0].closed is True

def test_runtime_lazily_constructs_user_client_for_masqueraded_message() -> None:
    runtime = FluxerDestinationRuntime(
        guild_id="guild-1",
        bot_client=FluxerClientConfig(token="bot-token"),
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "user-token"),
        ),
        client_factory=_factory(),
    )

    runtime.adapter.create_message(
        CanonicalMessage(
            id=MessageId("message-1"),
            conversation_id=ConversationId("conversation-1"),
            identity_key=IdentityKey("identity-1"),
            content="hello",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        DestinationConversationRef("channel-1"),
    )

    assert [instance.token for instance in FakeHTTPClient.instances] == [
        "bot-token",
        "user-token",
    ]
    assert FakeHTTPClient.instances[1].send_message_calls[0][0] == "channel-1"

    runtime.close()
    assert all(instance.closed for instance in FakeHTTPClient.instances)

def test_runtime_reuses_actor_client_for_multiple_operations() -> None:
    runtime = FluxerDestinationRuntime(
        guild_id="guild-1",
        bot_client=FluxerClientConfig(token="bot-token"),
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "user-token"),
        ),
        client_factory=_factory(),
    )

    from archive_sync_engine.adapters import DestinationConversationRef

    message = CanonicalMessage(
        id=MessageId("message-1"),
        conversation_id=ConversationId("conversation-1"),
        identity_key=IdentityKey("identity-1"),
        content="hello",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    runtime.adapter.create_message(
        message,
        DestinationConversationRef("channel-1"),
    )
    runtime.adapter.create_message(
        message.__class__(
            id=MessageId("message-2"),
            conversation_id=message.conversation_id,
            identity_key=message.identity_key,
            content="second",
            created_at=message.created_at,
        ),
        DestinationConversationRef("channel-1"),
    )

    assert [instance.token for instance in FakeHTTPClient.instances] == [
        "bot-token",
        "user-token",
    ]
    assert len(FakeHTTPClient.instances[1].send_message_calls) == 2

    runtime.close()
    assert all(instance.closed for instance in FakeHTTPClient.instances)


def test_runtime_wraps_client_factory_failures_as_adapter_error() -> None:
    factory = FluxerHttpClientFactory(
        importer=lambda: SimpleNamespace(
            HTTPClient=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("boom")
            ),
        ),
    )

    with pytest.raises(AdapterError, match="construct the Fluxer REST client"):
        FluxerDestinationRuntime(
            guild_id="guild-1",
            bot_client=FluxerClientConfig(token="bot-token"),
            client_factory=factory,
        )


def test_runtime_removes_one_existing_attachment_without_reuploading() -> None:
    runtime = FluxerDestinationRuntime(
        guild_id="guild-1",
        bot_client=FluxerClientConfig(token="bot-token"),
        client_factory=_factory(),
    )

    result = runtime._bot_client
    assert result is not None

    import asyncio
    asyncio.run(
        result.remove_attachment(
            "channel-1",
            "message-1",
            "remove.txt",
        )
    )

    client = FakeHTTPClient.instances[0]
    assert client.request_calls == [
        (
            "PATCH",
            "/channels/{channel_id}/messages/{message_id}",
            {"attachments": [{"id": "attachment-1", "filename": "keep.txt"}]},
        )
    ]

    runtime.close()


def test_runtime_rejects_ambiguous_attachment_filename() -> None:
    class AmbiguousHTTPClient(FakeHTTPClient):
        async def get_message(self, channel_id, message_id):
            return {
                "id": message_id,
                "channel_id": channel_id,
                "attachments": [
                    {"id": "attachment-1", "filename": "same.txt"},
                    {"id": "attachment-2", "filename": "same.txt"},
                ],
            }

    runtime = FluxerDestinationRuntime(
        guild_id="guild-1",
        bot_client=FluxerClientConfig(token="bot-token"),
        client_factory=FluxerHttpClientFactory(
            importer=lambda: SimpleNamespace(HTTPClient=AmbiguousHTTPClient),
        ),
    )

    import asyncio
    with pytest.raises(AdapterError, match="ambiguous"):
        asyncio.run(
            runtime._bot_client.remove_attachment(
                "channel-1",
                "message-1",
                "same.txt",
            )
        )

    runtime.close()




def test_build_fluxer_destination_runtime_config_uses_override_token() -> None:
    from archive_sync_engine.adapters.fluxer_runtime import build_fluxer_destination_runtime_config

    config = build_fluxer_destination_runtime_config(
        SimpleNamespace(fluxer_token="configured-token", identity_mappings=()),
        ("server-123",),
        {"token": "override-token", "max_retries": 2},
    )

    assert config["fluxer"].token == "override-token"
    assert config["fluxer"].max_retries == 2
