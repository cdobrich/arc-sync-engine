from __future__ import annotations

from archive_sync_engine.models.attachment import CanonicalAttachment
from archive_sync_engine.models.ids import MessageId
from archive_sync_engine.models.message import CanonicalMessage
from archive_sync_engine.models.reaction import CanonicalReaction

from .store import ArchiveStore
from archive_sync_engine.models.provenance import CanonicalProvenance


class ArchiveRecomposer:
    """
    Recompose canonical aggregates from normalized
    archive persistence.
    """

    def __init__(
        self,
        store: ArchiveStore,
    ) -> None:

        self._store = store

    def recompose_message(
        self,
        message_id: MessageId,
    ) -> CanonicalMessage:

        message = self._store.get_message(
            message_id,
        )

        if message is None:

            raise KeyError(
                f"Unknown message: {message_id}"
            )

        return CanonicalMessage(
            id=message.id,
            conversation_id=message.conversation_id,
            identity_key=message.identity_key,
            content=message.content,
            created_at=message.created_at,
            edited_at=message.edited_at,
            reply_to=message.reply_to,
            attachments=self._attachments(
                message.id,
            ),
            reactions=self._reactions(
                message.id,
            ),
        )

    def recompose_provenance(
            self,
    ) -> CanonicalProvenance:
        """
        Recompose the complete canonical provenance history
        from persistent archive storage.
        """

        return CanonicalProvenance(
            history=tuple(
                self._store.iter_provenance_transfers()
            ),
        )

    def _attachments(
        self,
        message_id: MessageId,
    ) -> tuple[CanonicalAttachment, ...]:

        return tuple(
            self._store.attachments_for_message(
                message_id,
            )
        )

    def _reactions(
        self,
        message_id: MessageId,
    ) -> tuple[CanonicalReaction, ...]:

        return tuple(
            self._store.reactions_for_message(
                message_id,
            )
        )