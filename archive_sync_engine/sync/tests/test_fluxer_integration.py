
"""End-to-end synchronization tests using the Fluxer destination adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from archive_sync_engine.adapters import (
    AdapterError,
    FluxerDestinationAdapter,
    FluxerIdentityMapping,
)
from archive_sync_engine.asset_store import AssetStore
from archive_sync_engine.models import CanonicalAttachment, CanonicalReaction
from archive_sync_engine.models.ids import AttachmentId
import hashlib
from archive_sync_engine.archive import Archive
from archive_sync_engine.executor import OperationExecutor
from archive_sync_engine.models import CanonicalConversation, CanonicalMessage
from archive_sync_engine.models.enums import ConversationType
from archive_sync_engine.models.ids import ConversationId, IdentityKey, MessageId
from archive_sync_engine.planner import Planner
from archive_sync_engine.repository import SQLiteStateRepository
from archive_sync_engine.sync.coordinator import SyncCoordinator
from archive_sync_engine.sync.fingerprint import canonical_fingerprint


class FakeFluxerClient:
    """Minimal async Fluxer client surface used by the integration tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self._next_message_id = 1
        self._next_channel_id = 1
        self.fail_apply_reaction = False

    async def _create_fluxer_channel_from_discord(
        self,
        channel_data: dict,
    ) -> dict[str, str]:
        channel_id = f"fluxer-channel-{self._next_channel_id}"
        self._next_channel_id += 1
        self.calls.append(
            ("create_conversation", (), dict(channel_data)),
        )
        return {"id": channel_id}

    async def send_message(
        self,
        channel_id: str,
        content: str,
        attachments=None,
        max_retries: int = 3,
        author_name: str | None = None,
        reply_to_id: str | None = None,
    ) -> dict[str, str]:
        message_id = f"fluxer-message-{self._next_message_id}"
        self._next_message_id += 1
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
        return {
            "id": message_id,
            "channel_id": channel_id,
        }

    async def edit_message(
        self,
        channel_id: str,
        message_id: str,
        new_content: str,
        new_attachments=None,
        max_retries: int = 3,
    ) -> bool:
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
    ) -> bool:
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

    async def delete_channel(self, channel_id: str) -> bool:
        self.calls.append(
            (
                "delete_channel",
                (channel_id,),
                {},
            ),
        )
        return True

    async def apply_reaction(
        self,
        channel_id: str,
        message_id: str,
        emoji: str,
        auth_key: str | None = None,
    ) -> bool:
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
            ),
        )
        return not self.fail_apply_reaction

    async def remove_reaction(
        self,
        channel_id: str,
        message_id: str,
        emoji_id_or_name: str,
        user_id: str = "@me",
        auth_key: str | None = None,
    ) -> bool:
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
            ),
        )
        return True

    async def pin_message(self, channel_id: str, message_id: str, max_retries: int = 3) -> bool:
        self.calls.append(
            (
                "pin_message",
                (),
                {"channel_id": channel_id, "message_id": message_id},
            ),
        )
        return True

    async def unpin_message(self, channel_id: str, message_id: str, max_retries: int = 3) -> bool:
        self.calls.append(
            (
                "unpin_message",
                (),
                {"channel_id": channel_id, "message_id": message_id},
            ),
        )
        return True


def _archive(
    conversation: CanonicalConversation,
    message: CanonicalMessage | None,
) -> Archive:
    archive = Mock(spec=Archive)
    archive.iter_identities.return_value = iter(())
    archive.iter_conversations.return_value = iter((conversation,))
    archive.iter_messages.return_value = (
        iter((message,)) if message is not None else iter(())
    )
    return archive


def _conversation() -> CanonicalConversation:
    return CanonicalConversation(
        id=ConversationId("conversation-1"),
        conversation_type=ConversationType.CHANNEL,
        title="general",
    )


def _message(
    content: str,
    *,
    reactions: tuple[CanonicalReaction, ...] = (),
) -> CanonicalMessage:
    return CanonicalMessage(
        id=MessageId("message-1"),
        conversation_id=ConversationId("conversation-1"),
        identity_key=IdentityKey("identity-1"),
        content=content,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reactions=reactions,
    )


def _coordinator(
    archive: Archive,
    client: FakeFluxerClient,
    repository: SQLiteStateRepository,
    *,
    asset_store: AssetStore | None = None,
    identity_mappings=(),
) -> SyncCoordinator:
    destination = FluxerDestinationAdapter(
        client,
        identity_mappings=identity_mappings,
    )
    return SyncCoordinator(
        archive=archive,
        planner=Planner(),
        executor=OperationExecutor(asset_store=asset_store),
        destination=destination,
        capabilities=destination.capabilities,
        state_repository=repository,
    )


def test_fluxer_initial_synchronization_persists_destination_references(
    tmp_path: Path,
) -> None:
    conversation = _conversation()
    message = _message("hello")
    archive = _archive(conversation, message)
    client = FakeFluxerClient()
    path = tmp_path / "state.sqlite3"

    with SQLiteStateRepository(path) as repository:
        _coordinator(archive, client, repository).synchronize()

    with SQLiteStateRepository(path) as repository:
        state = repository.load_synchronization_state()

    assert state.conversations["conversation-1"].id == "fluxer-channel-1"
    assert state.messages["message-1"].id == "fluxer-message-1"
    assert state.messages["message-1"].conversation_id == "fluxer-channel-1"
    assert state.message_fingerprints["message-1"]
    assert [call[0] for call in client.calls] == [
        "create_conversation",
        "send_message",
    ]


def test_fluxer_incremental_message_edit_uses_persisted_destination_reference(
    tmp_path: Path,
) -> None:
    conversation = _conversation()
    initial_message = _message("hello")
    path = tmp_path / "state.sqlite3"

    client = FakeFluxerClient()
    with SQLiteStateRepository(path) as repository:
        _coordinator(
            _archive(conversation, initial_message),
            client,
            repository,
        ).synchronize()

    client.calls.clear()
    updated_message = _message("updated")

    with SQLiteStateRepository(path) as repository:
        _coordinator(
            _archive(conversation, updated_message),
            client,
            repository,
        ).synchronize()

    assert client.calls == [
        (
            "edit_message",
            (),
            {
                "channel_id": "fluxer-channel-1",
                "message_id": "fluxer-message-1",
                "content": "updated",
            },
        ),
    ]


def test_fluxer_stale_message_is_deleted_before_stale_conversation(
    tmp_path: Path,
) -> None:
    conversation = _conversation()
    message = _message("hello")
    path = tmp_path / "state.sqlite3"

    client = FakeFluxerClient()
    with SQLiteStateRepository(path) as repository:
        _coordinator(
            _archive(conversation, message),
            client,
            repository,
        ).synchronize()

    client.calls.clear()
    empty_archive = _archive(conversation, None)
    empty_archive.iter_conversations.return_value = iter(())

    with SQLiteStateRepository(path) as repository:
        _coordinator(empty_archive, client, repository).synchronize()

    assert [call[0] for call in client.calls] == [
        "delete_message",
        "delete_channel",
    ]

    with SQLiteStateRepository(path) as repository:
        assert repository.load_synchronization_state().messages == {}
        assert repository.load_synchronization_state().conversations == {}


def test_fluxer_initial_pinned_message_is_synchronized(tmp_path: Path) -> None:
    conversation = _conversation()
    message = _message("hello")
    message = message.__class__(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content=message.content,
        created_at=message.created_at,
        pinned=True,
    )
    client = FakeFluxerClient()
    path = tmp_path / "state.sqlite3"

    with SQLiteStateRepository(path) as repository:
        _coordinator(
            _archive(conversation, message),
            client,
            repository,
        ).synchronize()

    assert [call[0] for call in client.calls] == [
        "create_conversation",
        "send_message",
        "pin_message",
    ]

    with SQLiteStateRepository(path) as repository:
        state = repository.load_synchronization_state()

    assert state.message_pinned["message-1"] is True
    assert state.message_fingerprints["message-1"]

def test_fluxer_pinned_message_can_be_unpinned_incrementally(tmp_path: Path) -> None:
    conversation = _conversation()
    pinned_message = _message("hello")
    pinned_message = pinned_message.__class__(
        id=pinned_message.id,
        conversation_id=pinned_message.conversation_id,
        identity_key=pinned_message.identity_key,
        content=pinned_message.content,
        created_at=pinned_message.created_at,
        pinned=True,
    )
    path = tmp_path / "state.sqlite3"
    client = FakeFluxerClient()

    with SQLiteStateRepository(path) as repository:
        _coordinator(
            _archive(conversation, pinned_message),
            client,
            repository,
        ).synchronize()

    client.calls.clear()
    unpinned_message = _message("hello")

    with SQLiteStateRepository(path) as repository:
        _coordinator(
            _archive(conversation, unpinned_message),
            client,
            repository,
        ).synchronize()

    assert client.calls == [
        (
            "unpin_message",
            (),
            {
                "channel_id": "fluxer-channel-1",
                "message_id": "fluxer-message-1",
            },
        ),
    ]

    with SQLiteStateRepository(path) as repository:
        state = repository.load_synchronization_state()

    assert state.message_pinned["message-1"] is False
    assert state.message_fingerprints["message-1"]

def test_fluxer_initial_reply_uses_existing_destination_reference(
    tmp_path: Path,
) -> None:
    conversation = _conversation()
    target = _message("target")
    initial_archive = Mock(spec=Archive)
    initial_archive.iter_identities.return_value = iter(())
    initial_archive.iter_conversations.return_value = iter((conversation,))
    initial_archive.iter_messages.return_value = iter((target,))

    client = FakeFluxerClient()
    path = tmp_path / "state.sqlite3"

    with SQLiteStateRepository(path) as repository:
        _coordinator(
            initial_archive,
            client,
            repository,
        ).synchronize()

    reply = CanonicalMessage(
        id=MessageId("message-2"),
        conversation_id=ConversationId("conversation-1"),
        identity_key=IdentityKey("identity-1"),
        content="reply",
        created_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        reply_to=target.id,
    )

    updated_archive = Mock(spec=Archive)
    updated_archive.iter_identities.return_value = iter(())
    updated_archive.iter_conversations.return_value = iter((conversation,))
    updated_archive.iter_messages.return_value = iter((target, reply))

    client.calls.clear()

    with SQLiteStateRepository(path) as repository:
        _coordinator(
            updated_archive,
            client,
            repository,
        ).synchronize()

    send_call = next(
        call for call in client.calls if call[0] == "send_message"
    )
    assert send_call[2]["reply_to_id"] == "fluxer-message-1"

    with SQLiteStateRepository(path) as repository:
        state = repository.load_synchronization_state()

    assert state.message_reply_to["message-2"] == target.id
    assert state.message_fingerprints["message-2"]

def test_fluxer_initial_message_attachment_is_synchronized_in_create(tmp_path: Path) -> None:
    conversation = _conversation()
    content = b"hello"
    attachment = CanonicalAttachment(
        id=AttachmentId("attachment-1"),
        filename="hello.txt",
        content_type="text/plain",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    message = _message("hello")
    message = message.__class__(
        id=message.id,
        conversation_id=message.conversation_id,
        identity_key=message.identity_key,
        content=message.content,
        created_at=message.created_at,
        attachments=(attachment,),
    )
    archive = _archive(conversation, message)
    client = FakeFluxerClient()
    path = tmp_path / "state.sqlite3"
    asset_store = AssetStore(tmp_path / "assets")
    asset_store.put_attachment(attachment, content)

    with SQLiteStateRepository(path) as repository:
        _coordinator(
            archive,
            client,
            repository,
            asset_store=asset_store,
        ).synchronize()

    send_call = next(call for call in client.calls if call[0] == "send_message")
    assert send_call[2]["attachments"] == [
        {"filename": "hello.txt", "data": content},
    ]

    with SQLiteStateRepository(path) as repository:
        state = repository.load_synchronization_state()

    assert state.message_attachments["message-1"] == (attachment,)
    assert state.message_fingerprints["message-1"]


def test_fluxer_reaction_masquerading_is_applied_and_removed_through_full_sync(
    tmp_path: Path,
) -> None:
    conversation = _conversation()
    reaction = CanonicalReaction(
        identity_key=IdentityKey("reactor-1"),
        emoji="👍",
        emoji_id=None,
        is_custom=False,
    )
    initial_message = _message("hello", reactions=(reaction,))
    path = tmp_path / "state.sqlite3"
    client = FakeFluxerClient()

    with SQLiteStateRepository(path) as repository:
        _coordinator(
            _archive(conversation, initial_message),
            client,
            repository,
            identity_mappings=(
                FluxerIdentityMapping(
                    "reactor-1",
                    "reactor-auth-key",
                ),
            ),
        ).synchronize()

    assert [call[0] for call in client.calls] == [
        "create_conversation",
        "send_message",
        "apply_reaction",
    ]
    assert client.calls[-1][2] == {
        "channel_id": "fluxer-channel-1",
        "message_id": "fluxer-message-1",
        "emoji": "👍",
        "auth_key": "reactor-auth-key",
    }

    client.calls.clear()
    updated_message = _message("hello")

    with SQLiteStateRepository(path) as repository:
        _coordinator(
            _archive(conversation, updated_message),
            client,
            repository,
            identity_mappings=(
                FluxerIdentityMapping(
                    "reactor-1",
                    "reactor-auth-key",
                ),
            ),
        ).synchronize()

    assert client.calls == [
        (
            "remove_reaction",
            (),
            {
                "channel_id": "fluxer-channel-1",
                "message_id": "fluxer-message-1",
                "emoji_id_or_name": "👍",
                "user_id": "@me",
                "auth_key": "reactor-auth-key",
            },
        ),
    ]

    with SQLiteStateRepository(path) as repository:
        state = repository.load_synchronization_state()

    assert state.message_reactions["message-1"] == ()
    assert state.message_fingerprints["message-1"] == (
        canonical_fingerprint(updated_message)
    )

def test_fluxer_reaction_failure_persists_partial_state_and_retries_only_reaction(
    tmp_path: Path,
) -> None:
    conversation = _conversation()
    target = _message("target")
    reaction = CanonicalReaction(
        identity_key=IdentityKey("reactor-1"),
        emoji="👍",
        emoji_id=None,
        is_custom=False,
    )
    reply = CanonicalMessage(
        id=MessageId("message-2"),
        conversation_id=ConversationId("conversation-1"),
        identity_key=IdentityKey("identity-1"),
        content="reply",
        created_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        reply_to=target.id,
        reactions=(reaction,),
    )
    path = tmp_path / "state.sqlite3"
    client = FakeFluxerClient()
    client.fail_apply_reaction = True
    mapping = (
        FluxerIdentityMapping(
            "reactor-1",
            "reactor-auth-key",
        ),
    )

    initial_archive = Mock(spec=Archive)
    initial_archive.iter_identities.return_value = iter(())
    initial_archive.iter_conversations.return_value = iter((conversation,))
    initial_archive.iter_messages.return_value = iter((target,))

    with SQLiteStateRepository(path) as repository:
        _coordinator(
            initial_archive,
            client,
            repository,
            identity_mappings=mapping,
        ).synchronize()

    updated_archive = Mock(spec=Archive)
    updated_archive.iter_identities.return_value = iter(())
    updated_archive.iter_conversations.return_value = iter((conversation,))
    updated_archive.iter_messages.return_value = iter((target, reply))

    with SQLiteStateRepository(path) as repository:
        with pytest.raises(AdapterError):
            _coordinator(
                updated_archive,
                client,
                repository,
                identity_mappings=mapping,
            ).synchronize()
        state = repository.load_synchronization_state()

    assert state.message_reply_to["message-2"] == target.id
    assert state.message_content_fingerprints["message-2"]
    assert "message-2" not in state.message_reactions
    assert "message-2" not in state.message_fingerprints
    assert [call[0] for call in client.calls[-2:]] == [
        "send_message",
        "apply_reaction",
    ]

    client.calls.clear()
    client.fail_apply_reaction = False
    updated_archive.iter_conversations.return_value = iter((conversation,))
    updated_archive.iter_messages.return_value = iter((target, reply))

    with SQLiteStateRepository(path) as repository:
        _coordinator(
            updated_archive,
            client,
            repository,
            identity_mappings=mapping,
        ).synchronize()

    assert [call[0] for call in client.calls] == ["apply_reaction"]

    with SQLiteStateRepository(path) as repository:
        state = repository.load_synchronization_state()

    assert state.message_reply_to["message-2"] == target.id
    assert state.message_reactions["message-2"] == (reaction,)
    assert state.message_fingerprints["message-2"] == canonical_fingerprint(reply)


def test_fluxer_initial_reply_and_reaction_complete_together(
    tmp_path: Path,
) -> None:
    conversation = _conversation()
    target = _message("target")
    reaction = CanonicalReaction(
        identity_key=IdentityKey("reactor-1"),
        emoji="👍",
        emoji_id=None,
        is_custom=False,
    )
    reply = CanonicalMessage(
        id=MessageId("message-2"),
        conversation_id=ConversationId("conversation-1"),
        identity_key=IdentityKey("identity-1"),
        content="reply",
        created_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        reply_to=target.id,
        reactions=(reaction,),
    )
    path = tmp_path / "state.sqlite3"
    client = FakeFluxerClient()
    mapping = (
        FluxerIdentityMapping(
            "reactor-1",
            "reactor-auth-key",
        ),
    )

    initial_archive = Mock(spec=Archive)
    initial_archive.iter_identities.return_value = iter(())
    initial_archive.iter_conversations.return_value = iter((conversation,))
    initial_archive.iter_messages.return_value = iter((target,))

    with SQLiteStateRepository(path) as repository:
        _coordinator(
            initial_archive,
            client,
            repository,
            identity_mappings=mapping,
        ).synchronize()

    client.calls.clear()
    combined_archive = Mock(spec=Archive)
    combined_archive.iter_identities.return_value = iter(())
    combined_archive.iter_conversations.return_value = iter((conversation,))
    combined_archive.iter_messages.return_value = iter((target, reply))

    with SQLiteStateRepository(path) as repository:
        _coordinator(
            combined_archive,
            client,
            repository,
            identity_mappings=mapping,
        ).synchronize()

    send_call = next(
        call for call in client.calls if call[0] == "send_message"
    )
    reaction_call = next(
        call for call in client.calls if call[0] == "apply_reaction"
    )

    assert send_call[2]["reply_to_id"] == "fluxer-message-1"
    assert reaction_call[2]["auth_key"] == "reactor-auth-key"

    with SQLiteStateRepository(path) as repository:
        state = repository.load_synchronization_state()

    assert state.message_reply_to["message-2"] == target.id
    assert state.message_reactions["message-2"] == (reaction,)
    assert state.message_fingerprints["message-2"] == canonical_fingerprint(reply)


