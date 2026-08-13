from archive_sync_engine.adapters.references import (
    DestinationAttachmentRef,
    DestinationConversationRef,
    DestinationIdentityRef,
    DestinationMessageRef,
)


def test_destination_conversation_ref_stores_identifier() -> None:
    reference = DestinationConversationRef(
        id="destination-conversation-123",
    )

    assert reference.id == "destination-conversation-123"


def test_destination_identity_ref_stores_identifier() -> None:
    reference = DestinationIdentityRef(
        id="destination-identity-123",
    )

    assert reference.id == "destination-identity-123"


def test_destination_message_ref_stores_identifier() -> None:
    reference = DestinationMessageRef(
        id="destination-message-123",
    )

    assert reference.id == "destination-message-123"
    assert reference.conversation_id is None

    channel_reference = DestinationMessageRef(
        id="destination-message-456",
        conversation_id="destination-conversation-123",
    )
    assert channel_reference.conversation_id == "destination-conversation-123"


def test_destination_attachment_ref_stores_identifier() -> None:
    reference = DestinationAttachmentRef(
        id="destination-attachment-123",
    )

    assert reference.id == "destination-attachment-123"