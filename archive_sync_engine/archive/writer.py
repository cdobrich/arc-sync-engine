"""
Archive Writer.

The ArchiveWriter incrementally assembles an immutable Archive.

Importers populate the writer while reading source systems.

The writer validates aggregate-wide invariants immediately before
producing the final Archive.
"""

from __future__ import annotations

from types import MappingProxyType

from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalIdentity,
    CanonicalMessage,
    CanonicalReaction,
)
from archive_sync_engine.models.ids import (
    AttachmentId,
    ConversationId,
    IdentityKey,
    MessageId,
)

from .archive import Archive
from .paths import ArchivePaths


class ArchiveWriter:
    """
    Mutable builder used to construct an immutable Archive.
    """
    def __init__(
        self,
        paths: ArchivePaths,
    ) -> None:

        self._paths = paths

        self._paths.ensure_exists()

        self._store = ArchiveStore.create(
            paths,
        )

    def add_conversation(
        self,
        conversation: CanonicalConversation,
    ) -> None:

        if conversation.id in self._conversations:
            raise ValueError(
                f"Duplicate conversation id: {conversation.id}"
            )

        self._conversations[conversation.id] = conversation
        
    def add_identity(
        self,
        identity: CanonicalIdentity,
    ) -> None:
        """
        Persist a canonical identity.
        """

        self._store.insert_identity(identity)
        
    
    def add_message(
        self,
        message: CanonicalMessage,
    ) -> None:

        if message.id in self._messages:
            raise ValueError(
                f"Duplicate message id: {message.id}"
            )

        self._messages[message.id] = message


    def add_attachment(
        self,
        attachment: CanonicalAttachment,
    ) -> None:

        if attachment.id in self._attachments:
            raise ValueError(
                f"Duplicate attachment id: {attachment.id}"
            )

        self._attachments[attachment.id] = attachment
        
        
    def add_reaction(
        self,
        reaction: CanonicalReaction,
    ) -> None:

        self._reactions.append(
            reaction,
        )

    def finalize(self) -> Archive:
        """
        Produce an immutable Archive.
        """

        self._validate()

        return Archive(
            _conversations=MappingProxyType(
                dict(self._conversations)
            ),
            _identities=MappingProxyType(
                dict(self._identities)
            ),
            _messages=MappingProxyType(
                dict(self._messages)
            ),
            _attachments=MappingProxyType(
                dict(self._attachments)
            ),
            _reactions=tuple(
                self._reactions
            ),
        )
  
    def _validate(self) -> None:
        """
        Validate aggregate-wide invariants.
        """

        #
        # Every message references an existing conversation.
        #

        for message in self._messages.values():

            if message.conversation_id not in self._conversations:

                raise ValueError(
                    f"Message {message.id} references "
                    f"unknown conversation "
                    f"{message.conversation_id}"
                )

        #
        # Every message references an existing identity.
        #

        for message in self._messages.values():

            if message.identity_key not in self._identities:

                raise ValueError(
                    f"Message {message.id} references "
                    f"unknown identity "
                    f"{message.identity_key}"
                )

        #
        # Every indexed attachment is referenced by at least one message.
        #

        referenced = {
            attachment.id
            for message in self._messages.values()
            for attachment in message.attachments
        }

        for attachment_id in self._attachments:

            if attachment_id not in referenced:

                raise ValueError(
                    f"Attachment {attachment_id} is "
                    f"not referenced by any message."
                )

        #
        # Every reaction references an existing message.
        #

        for reaction in self._reactions:

            if reaction.message_id not in self._messages:

                raise ValueError(
                    f"Reaction references unknown "
                    f"message {reaction.message_id}"
                )
