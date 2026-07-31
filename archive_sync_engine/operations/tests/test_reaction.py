from __future__ import annotations

from archive_sync_engine.models import CanonicalReaction
from archive_sync_engine.models.ids import IdentityKey, MessageId
from archive_sync_engine.operations import (
AddReactionOperation,
RemoveReactionOperation,
)

def test_add_reaction_operation_preserves_message_target() -> None:
    message_id = MessageId("message-001")

    reaction = CanonicalReaction(
        identity_key=IdentityKey("user-001"),
        emoji="👍",
    )

    operation = AddReactionOperation(
        message_id=message_id,
        reaction=reaction,
    )

    assert operation.message_id == message_id
    assert operation.reaction == reaction


def test_remove_reaction_operation_preserves_message_target() -> None:
    message_id = MessageId("message-002")


    reaction = CanonicalReaction(
        identity_key=IdentityKey("user-002"),
        emoji="❤️",
    )

    operation = RemoveReactionOperation(
        message_id=message_id,
        reaction=reaction,
    )

    assert operation.message_id == message_id
    assert operation.reaction == reaction