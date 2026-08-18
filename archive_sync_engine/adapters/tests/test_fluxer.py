from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from archive_sync_engine.adapters import (
    AdapterError,
    CapabilityError,
    DestinationConversationRef,
    DestinationMessageRef,
    FluxerDestinationAdapter,
    FluxerIdentityMapping,
)
from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalMessage,
    CanonicalReaction,
)
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.ids import (
    AttachmentId,
    ConversationId,
    EmojiId,
    IdentityKey,
    MessageId,
)


class FakeFluxerClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.send_result = {
            "id": "fluxer-message-1",
            "channel_id": "fluxer-channel-1",
        }

    async def _create_fluxer_channel_from_discord(self, channel_data):
        self.calls.append(("create_conversation", (), channel_data))
        return {"id": "fluxer-channel-1"}

    async def send_message(
        self,
        channel_id,
        content,
        attachments=None,
        max_retries=3,
        author_name=None,
        reply_to_id=None,
    ):
        self.calls.append(
            (
                "send_message",
                (),
                {
                    "channel_id": channel_id,
                    "content": content,
                    "attachments": attachments,
                    "author_name": author_name,
                    "reply_to_id": reply_to_id,
                },
            )
        )
        return self.send_result

    async def edit_message(
        self,
        channel_id,
        message_id,
        new_content,
        new_attachments=None,
        max_retries=3,
    ):
        self.calls.append(
            (
                "edit_message",
                (),
                {
                    "channel_id": channel_id,
                    "message_id": message_id,
                    "content": new_content,
                },
            )
        )
        return True

    async def delete_message(self, channel_id, message_id, max_retries=3):
        self.calls.append(
            (
                "delete_message",
                (),
                {"channel_id": channel_id, "message_id": message_id},
            )
        )
        return True

    async def delete_channel(self, channel_id):
        self.calls.append(("delete_channel", (channel_id,), {}))
        return True

    async def apply_reaction(
        self,
        channel_id,
        message_id,
        emoji,
        auth_key=None,
    ):
        self.calls.append(
            (
                "apply_reaction",
                (),
                {
                    "channel_id": channel_id,
                    "message_id": message_id,
                    "emoji": emoji,
                    "auth_key": auth_key,
                },
            )
        )
        return True

    async def remove_reaction(
        self,
        channel_id,
        message_id,
        emoji_id_or_name,
        user_id="@me",
        auth_key=None,
    ):
        self.calls.append(
            (
                "remove_reaction",
                (),
                {
                    "channel_id": channel_id,
                    "message_id": message_id,
                    "emoji_id_or_name": emoji_id_or_name,
                    "user_id": user_id,
                    "auth_key": auth_key,
                },
            )
        )
        return True

    async def remove_attachment(self, channel_id, message_id, filename):
        self.calls.append((
            "remove_attachment",
            (),
            {
                "channel_id": channel_id,
                "message_id": message_id,
                "filename": filename,
            },
        ))
        return True

    async def pin_message(self, channel_id, message_id, max_retries=3):
        self.calls.append(
            (
                "pin_message",
                (),
                {"channel_id": channel_id, "message_id": message_id},
            )
        )
        return True

    async def unpin_message(self, channel_id, message_id, max_retries=3):
        self.calls.append(
            (
                "unpin_message",
                (),
                {"channel_id": channel_id, "message_id": message_id},
            )
        )
        return True


def _message(*, content: str = "hello") -> CanonicalMessage:
    return CanonicalMessage(
        id=MessageId("message-1"),
        conversation_id=ConversationId("conversation-1"),
        identity_key=IdentityKey("identity-1"),
        content=content,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _attachment() -> CanonicalAttachment:
    return CanonicalAttachment(
        id=AttachmentId("attachment-1"),
        filename="hello.txt",
        content_type="text/plain",
        size=5,
        sha256="a" * 64,
    )


def _message_ref() -> DestinationMessageRef:
    return DestinationMessageRef(
        "fluxer-message-1",
        conversation_id="fluxer-channel-1",
    )


def test_fluxer_adapter_reports_current_capabilities() -> None:
    adapter = FluxerDestinationAdapter(
        FakeFluxerClient(),
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "auth-key"),
        ),
    )
    capabilities = adapter.capabilities

    assert capabilities.supports_threads is False
    assert capabilities.supports_message_editing is True
    assert capabilities.supports_conversation_updates is False
    assert capabilities.supports_message_deletion is True
    assert capabilities.supports_conversation_deletion is True
    assert capabilities.supports_message_pinning is True
    assert capabilities.supports_reactions is True
    assert capabilities.supports_custom_emoji is True
    assert capabilities.supports_attachments is False
    assert capabilities.supports_attachment_removal is True
    assert capabilities.supports_initial_message_attachments is True
    assert capabilities.supports_initial_message_replying is True
    assert capabilities.supports_replying is False
    assert capabilities.supports_identity_creation is False
    assert capabilities.supports_identity_mapping is True
    assert capabilities.supports_identity_updates is False
    assert capabilities.supports_identity_deletion is False


def test_fluxer_adapter_uses_injected_async_runner() -> None:
    calls: list[object] = []

    def run(awaitable):
        calls.append(awaitable)
        return asyncio.run(awaitable)

    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client, async_runner=run)

    result = adapter.create_conversation(
        CanonicalConversation(
            id=ConversationId("conversation-1"),
            conversation_type=ConversationType.CHANNEL,
            title="general",
        )
    )

    assert result.id == "fluxer-channel-1"
    assert len(calls) == 1
    assert client.calls[0][0] == "create_conversation"

def test_fluxer_adapter_reports_identity_mapping_unsupported_without_mappings() -> None:
    adapter = FluxerDestinationAdapter(FakeFluxerClient())

    assert adapter.capabilities.supports_identity_mapping is False


def test_create_conversation_maps_canonical_channel() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    conversation = CanonicalConversation(
        id=ConversationId("conversation-1"),
        conversation_type=ConversationType.CHANNEL,
        title="general",
    )

    result = adapter.create_conversation(conversation)

    assert result == DestinationConversationRef("fluxer-channel-1")
    assert client.calls == [
        (
            "create_conversation",
            (),
            {"name": "general", "type": 0},
        ),
    ]


def test_fluxer_thread_creation_is_explicitly_rejected_until_platform_support_exists() -> None:
    adapter = FluxerDestinationAdapter(FakeFluxerClient())
    thread = CanonicalConversation(
        id=ConversationId("thread-1"),
        conversation_type=ConversationType.THREAD,
        title="thread",
        parent_id=ConversationId("conversation-1"),
    )

    with pytest.raises(CapabilityError, match="does not currently support creating thread"):
        adapter.create_conversation(
            thread,
            DestinationConversationRef("fluxer-parent-channel"),
        )


def test_delete_conversation_uses_destination_reference() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    adapter.delete_conversation(DestinationConversationRef("fluxer-channel-1"))

    assert client.calls[-1] == (
        "delete_channel",
        ("fluxer-channel-1",),
        {},
    )


def test_create_message_returns_reference_with_conversation() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(
        client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "auth-key"),
        ),
    )

    result = adapter.create_message(
        _message(),
        DestinationConversationRef("fluxer-channel-1"),
    )

    assert result == DestinationMessageRef(
        "fluxer-message-1",
        conversation_id="fluxer-channel-1",
    )
    assert client.calls[-1][2]["author_name"] == "identity-1"
    assert client.calls[-1][2]["reply_to_id"] is None


def test_create_message_passes_initial_attachment_payload() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)
    attachment = _attachment()

    adapter.create_message(
        _message(),
        DestinationConversationRef("fluxer-channel-1"),
        ((attachment, b"hello"),),
    )

    assert client.calls[-1][2]["attachments"] == [
        {"filename": "hello.txt", "data": b"hello"},
    ]


def test_create_message_combines_initial_attachment_reply_and_masqueraded_author() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(
        client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "auth-key"),
        ),
    )
    attachment = _attachment()

    result = adapter.create_message(
        _message(),
        DestinationConversationRef("fluxer-channel-1"),
        ((attachment, b"hello"),),
        reply_to=DestinationMessageRef(
            "fluxer-parent-message",
            conversation_id="fluxer-channel-1",
        ),
    )

    assert result == DestinationMessageRef(
        "fluxer-message-1",
        conversation_id="fluxer-channel-1",
    )
    assert client.calls[-1] == (
        "send_message",
        (),
        {
            "channel_id": "fluxer-channel-1",
            "content": "hello",
            "attachments": [
                {
                    "filename": "hello.txt",
                    "data": b"hello",
                },
            ],
            "author_name": "identity-1",
            "reply_to_id": "fluxer-parent-message",
        },
    )


def test_edit_message_uses_persisted_conversation_id() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    adapter.edit_message(_message(content="updated"), _message_ref())

    assert client.calls[-1][2] == {
        "channel_id": "fluxer-channel-1",
        "message_id": "fluxer-message-1",
        "content": "updated",
    }


def test_delete_message_uses_persisted_conversation_id() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    adapter.delete_message(_message_ref())

    assert client.calls[-1][0] == "delete_message"
    assert client.calls[-1][2]["channel_id"] == "fluxer-channel-1"


def test_pin_and_unpin_use_persisted_conversation_id() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    adapter.pin_message(_message_ref())
    adapter.unpin_message(_message_ref())

    assert [call[0] for call in client.calls] == [
        "pin_message",
        "unpin_message",
    ]


def test_capabilities_advertise_standard_reaction_synchronization_only_with_mappings() -> None:
    assert (
        FluxerDestinationAdapter(FakeFluxerClient())
        .capabilities
        .supports_reactions
        is False
    )

    adapter = FluxerDestinationAdapter(
        FakeFluxerClient(),
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "auth-key"),
        ),
    )

    assert adapter.capabilities.supports_reactions is True
    assert adapter.capabilities.supports_custom_emoji is True




def test_identity_mapping_rejects_empty_auth_key() -> None:
    with pytest.raises(ValueError, match="auth key"):
        FluxerIdentityMapping("identity-1", "")


def test_identity_mapping_rejects_empty_username() -> None:
    with pytest.raises(ValueError, match="username"):
        FluxerIdentityMapping("", "auth-key")


def test_duplicate_identity_mappings_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate.*identity"):
        FluxerDestinationAdapter(
            FakeFluxerClient(),
            identity_mappings=(
                FluxerIdentityMapping("identity-1", "auth-key-1"),
                FluxerIdentityMapping("identity-1", "auth-key-2"),
            ),
        )


def test_standard_reaction_requires_identity_mapping() -> None:
    adapter = FluxerDestinationAdapter(FakeFluxerClient())

    with pytest.raises(CapabilityError, match="identity mapping"):
        adapter.add_reaction(
            _message_ref(),
            CanonicalReaction(
                identity_key=IdentityKey("identity-1"),
                emoji="👍",
                emoji_id=None,
                is_custom=False,
            ),
        )


def test_standard_reaction_rejects_unmapped_actor_even_when_other_mappings_exist() -> None:
    adapter = FluxerDestinationAdapter(
        FakeFluxerClient(),
        identity_mappings=(
            FluxerIdentityMapping("other-identity", "other-auth-key"),
        ),
    )

    with pytest.raises(CapabilityError, match="identity mapping"):
        adapter.add_reaction(
            _message_ref(),
            CanonicalReaction(
                identity_key=IdentityKey("identity-1"),
                emoji="👍",
                emoji_id=None,
                is_custom=False,
            ),
        )


def test_standard_reaction_is_forwarded() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(
        client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "auth-key"),
        ),
    )

    adapter.add_reaction(
        _message_ref(),
        CanonicalReaction(
            identity_key=IdentityKey("identity-1"),
            emoji="👍",
            emoji_id=None,
            is_custom=False,
        ),
    )

    assert client.calls[-1][2] == {
        "channel_id": "fluxer-channel-1",
        "message_id": "fluxer-message-1",
        "emoji": "👍",
        "auth_key": "auth-key",
    }




def test_standard_reaction_can_use_the_default_bot_account() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(
        client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1"),
        ),
    )

    adapter.add_reaction(
        _message_ref(),
        CanonicalReaction(
            identity_key=IdentityKey("identity-1"),
            emoji="👍",
            emoji_id=None,
            is_custom=False,
        ),
    )

    assert client.calls[-1][2]["auth_key"] is None


def test_standard_reaction_uses_masquerade_auth_key() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(
        client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "user-auth-key"),
        ),
    )

    adapter.add_reaction(
        _message_ref(),
        CanonicalReaction(
            identity_key=IdentityKey("identity-1"),
            emoji="👍",
            emoji_id=None,
            is_custom=False,
        ),
    )

    assert client.calls[-1][2]["auth_key"] == "user-auth-key"


def test_reaction_removal_uses_masquerade_auth_key() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(
        client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "user-auth-key"),
        ),
    )

    adapter.remove_reaction(
        _message_ref(),
        CanonicalReaction(
            identity_key=IdentityKey("identity-1"),
            emoji="👍",
            emoji_id=None,
            is_custom=False,
        ),
    )

    assert client.calls[-1][2]["auth_key"] == "user-auth-key"


def test_custom_reaction_is_forwarded_with_name_and_id() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(
        client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "auth-key"),
        ),
    )

    adapter.add_reaction(
        _message_ref(),
        CanonicalReaction(
            identity_key=IdentityKey("identity-1"),
            emoji="party_parrot",
            emoji_id=EmojiId("1234567890"),
            is_custom=True,
        ),
    )

    assert client.calls[-1][2]["emoji"] == "party_parrot:1234567890"
    assert client.calls[-1][2]["auth_key"] == "auth-key"


def test_custom_reaction_removal_is_forwarded_with_name_and_id() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(
        client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "auth-key"),
        ),
    )

    adapter.remove_reaction(
        _message_ref(),
        CanonicalReaction(
            identity_key=IdentityKey("identity-1"),
            emoji="party_parrot",
            emoji_id=EmojiId("1234567890"),
            is_custom=True,
        ),
    )

    assert client.calls[-1][2]["emoji_id_or_name"] == "party_parrot:1234567890"
    assert client.calls[-1][2]["auth_key"] == "auth-key"

def test_custom_reaction_requires_emoji_id() -> None:
    adapter = FluxerDestinationAdapter(
        FakeFluxerClient(),
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "auth-key"),
        ),
    )

    with pytest.raises(ValueError, match="emoji_id"):
        adapter.add_reaction(
            _message_ref(),
            CanonicalReaction(
                identity_key=IdentityKey("identity-1"),
                emoji="custom",
                emoji_id=None,
                is_custom=True,
            ),
        )


def test_custom_reaction_can_use_the_default_bot_account() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(
        client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1"),
        ),
    )

    adapter.add_reaction(
        _message_ref(),
        CanonicalReaction(
            identity_key=IdentityKey("identity-1"),
            emoji="party_parrot",
            emoji_id=EmojiId("1234567890"),
            is_custom=True,
        ),
    )

    assert client.calls[-1][2]["emoji"] == "party_parrot:1234567890"
    assert client.calls[-1][2]["auth_key"] is None


def test_reaction_client_factory_failure_is_reported_as_adapter_error() -> None:
    def factory(auth_key: str):
        raise RuntimeError("client construction failed")

    adapter = FluxerDestinationAdapter(
        FakeFluxerClient(),
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "user-auth-key"),
        ),
        reaction_client_factory=factory,
    )

    with pytest.raises(AdapterError, match="actor client could not be created"):
        adapter.add_reaction(
            _message_ref(),
            CanonicalReaction(
                identity_key=IdentityKey("identity-1"),
                emoji="party_parrot",
                emoji_id=EmojiId("123"),
                is_custom=True,
            ),
        )


def test_reaction_client_factory_returning_none_is_reported_as_adapter_error() -> None:
    adapter = FluxerDestinationAdapter(
        FakeFluxerClient(),
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "user-auth-key"),
        ),
        reaction_client_factory=lambda auth_key: None,
    )

    with pytest.raises(AdapterError, match="actor client factory returned no client"):
        adapter.add_reaction(
            _message_ref(),
            CanonicalReaction(
                identity_key=IdentityKey("identity-1"),
                emoji="party_parrot",
                emoji_id=EmojiId("123"),
                is_custom=True,
            ),
        )


def test_reaction_client_factory_selects_masqueraded_fluxer_client() -> None:
    default_client = FakeFluxerClient()
    user_client = FakeFluxerClient()
    factory_calls: list[str] = []

    def factory(auth_key: str) -> FakeFluxerClient:
        factory_calls.append(auth_key)
        return user_client

    adapter = FluxerDestinationAdapter(
        default_client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "user-auth-key"),
        ),
        reaction_client_factory=factory,
    )

    adapter.add_reaction(
        _message_ref(),
        CanonicalReaction(
            identity_key=IdentityKey("identity-1"),
            emoji="party_parrot",
            emoji_id=EmojiId("1234567890"),
            is_custom=True,
        ),
    )

    assert factory_calls == ["user-auth-key"]
    assert default_client.calls == []
    assert user_client.calls[-1][2]["emoji"] == "party_parrot:1234567890"
    assert user_client.calls[-1][2]["auth_key"] is None


def test_custom_reaction_uses_actor_client_factory_for_add_and_remove() -> None:
    bot_client = FakeFluxerClient()
    user_client = FakeFluxerClient()
    created_auth_keys: list[str] = []

    def factory(auth_key: str):
        created_auth_keys.append(auth_key)
        return user_client

    adapter = FluxerDestinationAdapter(
        bot_client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "user-auth-key"),
        ),
        reaction_client_factory=factory,
    )
    reaction = CanonicalReaction(
        identity_key=IdentityKey("identity-1"),
        emoji="party_parrot",
        emoji_id=EmojiId("123"),
        is_custom=True,
    )

    adapter.add_reaction(_message_ref(), reaction)
    adapter.remove_reaction(_message_ref(), reaction)

    assert created_auth_keys == ["user-auth-key", "user-auth-key"]
    assert [call[0] for call in user_client.calls] == [
        "apply_reaction",
        "remove_reaction",
    ]
    assert user_client.calls[0][2]["emoji"] == "party_parrot:123"
    assert user_client.calls[1][2]["emoji_id_or_name"] == "party_parrot:123"
    assert bot_client.calls == []


def test_unsupported_attachment_mutation_is_rejected() -> None:
    adapter = FluxerDestinationAdapter(FakeFluxerClient())

    with pytest.raises(CapabilityError):
        adapter.add_attachment(_message_ref(), _attachment(), b"hello")


def test_unsupported_reply_is_rejected() -> None:
    adapter = FluxerDestinationAdapter(FakeFluxerClient())

    with pytest.raises(CapabilityError):
        adapter.set_message_reply(_message_ref(), _message_ref())


def test_identity_creation_is_rejected() -> None:
    adapter = FluxerDestinationAdapter(FakeFluxerClient())

    from archive_sync_engine.models import CanonicalIdentity

    with pytest.raises(CapabilityError):
        adapter.create_identity(
            CanonicalIdentity(
                identity_key=IdentityKey("identity-1"),
                display_name="identity-1",
            )
        )


def test_conversation_update_is_rejected() -> None:
    adapter = FluxerDestinationAdapter(FakeFluxerClient())
    conversation = CanonicalConversation(
        id=ConversationId("conversation-1"),
        conversation_type=ConversationType.CHANNEL,
        title="general",
    )

    with pytest.raises(CapabilityError):
        adapter.update_conversation(
            conversation,
            DestinationConversationRef("fluxer-channel-1"),
        )


def test_failed_message_creation_raises_adapter_error() -> None:
    client = FakeFluxerClient()
    client.send_result = None
    adapter = FluxerDestinationAdapter(client)

    with pytest.raises(AdapterError):
        adapter.create_message(
            _message(),
            DestinationConversationRef("fluxer-channel-1"),
        )


def test_adapter_rejects_use_inside_running_event_loop() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    async def invoke() -> None:
        with pytest.raises(RuntimeError):
            adapter.create_message(
                _message(),
                DestinationConversationRef("fluxer-channel-1"),
            )

    asyncio.run(invoke())


def test_create_message_passes_initial_attachment_payload_to_fluxer() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)
    attachment = _attachment()
    content = b"hello"

    adapter.create_message(
        _message(),
        DestinationConversationRef("fluxer-channel-1"),
        ((attachment, content),),
    )

    assert client.calls[-1][0] == "send_message"
    assert client.calls[-1][2]["attachments"] == [
        {
            "filename": "hello.txt",
            "data": content,
        },
    ]


def test_create_message_passes_initial_reply_reference_to_fluxer() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    message = _message()
    adapter.create_message(
        message,
        DestinationConversationRef("fluxer-channel-1"),
        reply_to=DestinationMessageRef(
            "fluxer-parent-message",
            conversation_id="fluxer-channel-1",
        ),
    )

    assert client.calls[-1][2]["reply_to_id"] == "fluxer-parent-message"


def test_reaction_add_failure_is_reported_as_adapter_error() -> None:
    client = FakeFluxerClient()

    async def failing_apply_reaction(*args, **kwargs):
        client.calls.append(("apply_reaction", args, kwargs))
        return False

    client.apply_reaction = failing_apply_reaction

    adapter = FluxerDestinationAdapter(
        client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1", None),
        ),
    )

    with pytest.raises(AdapterError, match="add reaction"):
        adapter.add_reaction(
            _message_ref(),
            CanonicalReaction(
                identity_key=IdentityKey("identity-1"),
                emoji="👍",
                emoji_id=None,
                is_custom=False,
            ),
        )


def test_reaction_removal_failure_is_reported_as_adapter_error() -> None:
    client = FakeFluxerClient()

    async def failing_remove_reaction(*args, **kwargs):
        client.calls.append(("remove_reaction", args, kwargs))
        return False

    client.remove_reaction = failing_remove_reaction

    adapter = FluxerDestinationAdapter(
        client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "auth-key"),
        ),
    )

    with pytest.raises(AdapterError, match="remove reaction"):
        adapter.remove_reaction(
            _message_ref(),
            CanonicalReaction(
                identity_key=IdentityKey("identity-1"),
                emoji="👍",
                emoji_id=None,
                is_custom=False,
            ),
        )


def test_reaction_add_requires_destination_conversation_reference() -> None:
    adapter = FluxerDestinationAdapter(
        FakeFluxerClient(),
        identity_mappings=(
            FluxerIdentityMapping("identity-1", None),
        ),
    )

    with pytest.raises(AdapterError, match="missing conversation_id"):
        adapter.add_reaction(
            DestinationMessageRef("fluxer-message-1"),
            CanonicalReaction(
                identity_key=IdentityKey("identity-1"),
                emoji="👍",
                emoji_id=None,
                is_custom=False,
            ),
        )


def test_reaction_removal_requires_destination_conversation_reference() -> None:
    adapter = FluxerDestinationAdapter(
        FakeFluxerClient(),
        identity_mappings=(
            FluxerIdentityMapping("identity-1", None),
        ),
    )

    with pytest.raises(AdapterError, match="missing conversation_id"):
        adapter.remove_reaction(
            DestinationMessageRef("fluxer-message-1"),
            CanonicalReaction(
                identity_key=IdentityKey("identity-1"),
                emoji="👍",
                emoji_id=None,
                is_custom=False,
            ),
        )



def test_message_actor_masquerading_uses_identity_client_factory() -> None:
    bot_client = FakeFluxerClient()
    user_client = FakeFluxerClient()
    captured_mappings = []

    def factory(mapping: FluxerIdentityMapping):
        captured_mappings.append(mapping)
        return user_client

    adapter = FluxerDestinationAdapter(
        bot_client,
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "user-auth-key"),
        ),
        identity_client_factory=factory,
    )

    adapter.create_message(
        _message(),
        DestinationConversationRef("fluxer-channel-1"),
    )

    assert captured_mappings == [
        FluxerIdentityMapping("identity-1", "user-auth-key"),
    ]
    assert user_client.calls[-1][0] == "send_message"
    assert bot_client.calls == []
    assert user_client.calls[-1][2]["author_name"] == "identity-1"


def test_message_actor_masquerading_factory_failure_is_reported() -> None:
    def factory(mapping: FluxerIdentityMapping):
        raise RuntimeError("client construction failed")

    adapter = FluxerDestinationAdapter(
        FakeFluxerClient(),
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "user-auth-key"),
        ),
        identity_client_factory=factory,
    )

    with pytest.raises(AdapterError, match="Failed to create Fluxer client"):
        adapter.create_message(
            _message(),
            DestinationConversationRef("fluxer-channel-1"),
        )


def test_remove_attachment_uses_destination_message_reference() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    attachment = CanonicalAttachment(
        id=AttachmentId("attachment-1"),
        filename="hello.txt",
        content_type="text/plain",
        size=5,
        sha256="a" * 64,
    )

    adapter.remove_attachment(
        DestinationMessageRef("fluxer-message-1", conversation_id="fluxer-channel-1"),
        attachment,
    )

    assert client.calls[-1] == (
        "remove_attachment",
        (),
        {
            "channel_id": "fluxer-channel-1",
            "message_id": "fluxer-message-1",
            "filename": "hello.txt",
        },
    )
