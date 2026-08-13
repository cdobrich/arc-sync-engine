# archive_sync_engine/adapters/tests/test_fluxer.py

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from archive_sync_engine.adapters.fluxer import FluxerDestinationAdapter
from archive_sync_engine.adapters.exceptions import (
    AdapterError,
    CapabilityError,
)
from archive_sync_engine.adapters.references import (
    DestinationConversationRef,
    DestinationMessageRef,
)
from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalMessage,
    CanonicalReaction,
)
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

    async def create_conversation(
        self,
        name: str,
        channel_type: int,
    ):
        self.calls.append(
            ("create_conversation", (name, channel_type), {}),
        )
        return {"id": "fluxer-channel-1"}

    async def send_message(
        self,
        channel_id: str,
        content: str,
        attachments=None,
        max_retries: int = 3,
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
            ),
        )
        return self.send_result

    async def edit_message(
        self,
        channel_id: str,
        message_id: str,
        new_content: str,
        new_attachments=None,
        max_retries: int = 3,
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
            ),
        )
        return True

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
        max_retries: int = 3,
    ):
        self.calls.append(
            (
                "delete_message",
                (),
                {
                    "channel_id": channel_id,
                    "message_id": message_id,
                },
            ),
        )
        return True

    async def delete_channel(self, channel_id: str):
        self.calls.append(
            ("delete_channel", (channel_id,), {}),
        )
        return True

    async def pin_message(
        self,
        channel_id: str,
        message_id: str,
        max_retries: int = 3,
    ):
        self.calls.append(
            (
                "pin_message",
                (),
                {
                    "channel_id": channel_id,
                    "message_id": message_id,
                },
            ),
        )
        return True

    async def unpin_message(
        self,
        channel_id: str,
        message_id: str,
        max_retries: int = 3,
    ):
        self.calls.append(
            (
                "unpin_message",
                (),
                {
                    "channel_id": channel_id,
                    "message_id": message_id,
                },
            ),
        )
        return True

    async def apply_reaction(
        self,
        channel_id: str,
        message_id: str,
        emoji: str,
    ):
        self.calls.append(
            (
                "apply_reaction",
                (),
                {
                    "channel_id": channel_id,
                    "message_id": message_id,
                    "emoji": emoji,
                },
            ),
        )
        return True

    async def remove_reaction(
        self,
        channel_id: str,
        message_id: str,
        emoji_id_or_name: str,
        user_id: str = "@me",
    ):
        self.calls.append(
            (
                "remove_reaction",
                (),
                {
                    "channel_id": channel_id,
                    "message_id": message_id,
                    "emoji_id_or_name": emoji_id_or_name,
                },
            ),
        )
        return True


def _message(
    *,
    content: str = "hello",
) -> CanonicalMessage:
    return CanonicalMessage(
        id=MessageId("message-1"),
        conversation_id=ConversationId("conversation-1"),
        identity_key=IdentityKey("identity-1"),
        content=content,
        created_at=datetime(
            2026,
            1,
            1,
            tzinfo=timezone.utc,
        ),
    )


def test_create_message_returns_fluxer_message_reference_with_channel() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    result = adapter.create_message(
        _message(),
        DestinationConversationRef("fluxer-channel-1"),
    )

    assert result == DestinationMessageRef(
        "fluxer-message-1",
        conversation_id="fluxer-channel-1",
    )

    assert client.calls == [
        (
            "send_message",
            (),
            {
                "channel_id": "fluxer-channel-1",
                "content": "hello",
                "attachments": None,
                "author_name": None,
                "reply_to_id": None,
            },
        ),
    ]


def test_create_message_passes_attachment_bytes_to_fluxer() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    attachment = CanonicalAttachment(
        id=AttachmentId("attachment-1"),
        filename="hello.txt",
        content_type="text/plain",
        size=5,
        sha256="a" * 64,
    )

    adapter.create_message(
        _message(),
        DestinationConversationRef("fluxer-channel-1"),
        ((attachment, b"hello"),),
    )

    assert client.calls[0][2]["attachments"] == [
        {
            "filename": "hello.txt",
            "data": b"hello",
        },
    ]


def test_edit_message_uses_persisted_conversation_id() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    adapter.edit_message(
        _message(content="updated"),
        DestinationMessageRef(
            "fluxer-message-1",
            conversation_id="fluxer-channel-1",
        ),
    )

    assert client.calls[-1] == (
        "edit_message",
        (),
        {
            "channel_id": "fluxer-channel-1",
            "message_id": "fluxer-message-1",
            "content": "updated",
        },
    )


def test_delete_message_uses_persisted_conversation_id() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    adapter.delete_message(
        DestinationMessageRef(
            "fluxer-message-1",
            conversation_id="fluxer-channel-1",
        ),
    )

    assert client.calls[-1][0] == "delete_message"
    assert client.calls[-1][2]["channel_id"] == "fluxer-channel-1"


def test_pin_and_unpin_use_persisted_conversation_id() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    message = DestinationMessageRef(
        "fluxer-message-1",
        conversation_id="fluxer-channel-1",
    )

    adapter.pin_message(message)
    adapter.unpin_message(message)

    assert [call[0] for call in client.calls] == [
        "pin_message",
        "unpin_message",
    ]


def test_standard_reaction_is_forwarded() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    adapter.add_reaction(
        DestinationMessageRef(
            "fluxer-message-1",
            conversation_id="fluxer-channel-1",
        ),
        CanonicalReaction(
            identity_key=IdentityKey("identity-1"),
            emoji="👍",
            emoji_id=None,
            is_custom=False,
        ),
    )

    assert client.calls[-1][2]["emoji"] == "👍"


def test_custom_reaction_is_rejected() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    with pytest.raises(CapabilityError):
        adapter.add_reaction(
            DestinationMessageRef(
                "fluxer-message-1",
                conversation_id="fluxer-channel-1",
            ),
            CanonicalReaction(
                identity_key=IdentityKey("identity-1"),
                emoji="custom",
                emoji_id=EmojiId("emoji-1"),
                is_custom=True,
            ),
        )


def test_attachment_mutation_is_rejected() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    attachment = CanonicalAttachment(
        id=AttachmentId("attachment-1"),
        filename="hello.txt",
        content_type="text/plain",
        size=5,
        sha256="a" * 64,
    )

    with pytest.raises(CapabilityError):
        adapter.add_attachment(
            DestinationMessageRef(
                "fluxer-message-1",
                conversation_id="fluxer-channel-1",
            ),
            attachment,
            b"hello",
        )


def test_reply_is_rejected_until_fluxer_reply_slice_exists() -> None:
    client = FakeFluxerClient()
    adapter = FluxerDestinationAdapter(client)

    with pytest.raises(CapabilityError):
        adapter.set_message_reply(
            DestinationMessageRef(
                "fluxer-message-1",
                conversation_id="fluxer-channel-1",
            ),
            DestinationMessageRef(
                "fluxer-message-2",
                conversation_id="fluxer-channel-1",
            ),
        )


def test_fluxer_failure_does_not_return_success() -> None:
    client = FakeFluxerClient()
    client.send_result = None

    adapter = FluxerDestinationAdapter(client)

    with pytest.raises(AdapterError):
        adapter.create_message(
            _message(),
            DestinationConversationRef("fluxer-channel-1"),
        )