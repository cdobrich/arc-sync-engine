"""
Abstract source adapter interface.

A SourceAdapter reads data from a source platform and translates it into
canonical models understood by the Archive Engine.

Source adapters are responsible only for reading platform state.
They never perform write operations.

All platform-specific representations must be converted into canonical
models before crossing the adapter boundary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from archive_sync_engine.models import (
    CanonicalAttachment,
    CanonicalConversation,
    CanonicalCustomEmoji,
    CanonicalIdentity,
    CanonicalMessage,
)


@dataclass(frozen=True, slots=True)
class SourceRefreshCursor:
    """Adapter-neutral high-water mark for incremental source refreshes.

    The cursor identifies the newest source message already committed for a
    conversation.  Adapters may use the timestamp and stable message ID to
    translate it into their native incremental-history API.
    """

    created_at: datetime
    message_id: str

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Source refresh cursor timestamps must be timezone-aware.")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
            "message_id": self.message_id,
        }

    @classmethod
    def from_json_dict(cls, data: Any) -> "SourceRefreshCursor":
        if not isinstance(data, dict):
            raise ValueError("Source refresh cursor must be a JSON object.")
        created_at = datetime.fromisoformat(str(data["created_at"]))
        message_id = str(data["message_id"])
        if not message_id:
            raise ValueError("Source refresh cursor message_id must not be empty.")
        return cls(created_at=created_at, message_id=message_id)


@dataclass(frozen=True, slots=True)
class IdentityDiscoveryBatch:
    """One bounded, resumable unit of source identity discovery."""

    identities: tuple[CanonicalIdentity, ...]
    cursor: Mapping[str, Any] = field(default_factory=dict)
    complete: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.identities, tuple):
            raise TypeError("Identity discovery batch identities must be a tuple.")
        if not isinstance(self.cursor, Mapping):
            raise TypeError("Identity discovery batch cursor must be a mapping.")



class SourceAdapter(ABC):
    """
    Abstract interface implemented by every source platform adapter.

    The Archive Engine communicates exclusively through this interface
    when importing data from a platform.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Human-readable adapter name.

        Examples:

            "Discord"
            "Fluxer"
        """
        raise NotImplementedError

    @abstractmethod
    def iter_conversations(self) -> Iterable[CanonicalConversation]:
        """
        Enumerate every conversation available from the source.
        """
        raise NotImplementedError

    @abstractmethod
    def iter_identities(self) -> Iterable[CanonicalIdentity]:
        """
        Enumerate every logical identity referenced by the source.
        """
        raise NotImplementedError

    def iter_custom_emojis(self) -> Iterable[CanonicalCustomEmoji]:
        """Enumerate custom emojis that are part of the source archive scope."""
        return ()

    def custom_emoji_bytes(
        self,
        emoji: CanonicalCustomEmoji,
    ) -> bytes:
        """Retrieve archived source bytes for a canonical custom emoji."""
        raise NotImplementedError(
            f"Source adapter {self.name!r} does not provide custom emoji bytes."
        )

    def iter_messages(
        self,
        conversation: CanonicalConversation,
    ) -> Iterable[CanonicalMessage]:
        """
        Enumerate every message belonging to a conversation.
        """
        raise NotImplementedError

    def iter_messages_by_ids(
        self,
        conversation: CanonicalConversation,
        message_ids: Iterable[str],
    ) -> Iterable[CanonicalMessage]:
        """Retrieve selected messages for demand-driven relationship recovery.

        Adapters with a native point-lookup API should override this method.
        The compatibility fallback filters a full conversation traversal.
        """
        wanted = {str(message_id) for message_id in message_ids}
        if not wanted:
            return
        for message in self.iter_messages(conversation):
            message_id = str(message.id)
            if message_id in wanted:
                yield message
                wanted.discard(message_id)
                if not wanted:
                    break

    def iter_pinned_message_ids(
        self,
        conversation: CanonicalConversation,
    ) -> Iterable[str] | None:
        """Return canonical message IDs currently pinned in a conversation.

        Pin state is channel-scoped mutable state. It can change for an
        arbitrarily old message without changing the message's creation
        position, so incremental message traversal alone cannot reliably
        refresh it. Adapters with an authoritative pin collection can
        override this method.
        """
        del conversation
        return None

    def iter_messages_after_checkpoint(
        self,
        conversation: CanonicalConversation,
        cursor: SourceRefreshCursor,
    ) -> Iterable[CanonicalMessage]:
        """Enumerate messages strictly after a committed full-import cursor.

        This cursor is a recovery boundary, not an incremental-refresh
        lookback window. Adapters may use a native ``after`` traversal to
        avoid replaying the already committed historical prefix. The base
        implementation preserves compatibility by falling back to complete
        traversal; callers retain the persisted message ID as a safety net.
        """
        del cursor
        yield from self.iter_messages(conversation)

    def iter_messages_since(
        self,
        conversation: CanonicalConversation,
        cursor: SourceRefreshCursor,
    ) -> Iterable[CanonicalMessage]:
        """Enumerate messages after a persisted refresh cursor.

        The base implementation deliberately falls back to the complete
        conversation traversal.  This keeps incremental refresh safe for
        adapters that do not yet expose a native incremental API.
        """
        yield from self.iter_messages(conversation)

    def iter_message_identities(
        self,
        message: CanonicalMessage,
    ) -> Iterable[CanonicalIdentity]:
        """Return identities discovered while canonicalizing one message."""
        del message
        return ()

    def iter_identities_since(
        self,
        cursors: Mapping[str, SourceRefreshCursor],
    ) -> Iterable[CanonicalIdentity]:
        """Enumerate identities relevant to an incremental refresh.

        Adapters without an optimized identity traversal safely fall back to
        their complete identity enumeration.
        """
        yield from self.iter_identities()

    def iter_identity_batches(
        self,
        *,
        resume_cursor: Mapping[str, Any] | None = None,
        batch_size: int = 100,
    ) -> Iterable[IdentityDiscoveryBatch]:
        """Enumerate identities in bounded, resumable discovery batches.

        The default implementation preserves the existing adapter contract.
        Adapters that can checkpoint their traversal should override this
        method and place only JSON-serializable source traversal data in the
        returned cursor.
        """
        if batch_size <= 0:
            raise ValueError("Identity discovery batch size must be greater than zero.")
        del resume_cursor
        batch: list[CanonicalIdentity] = []
        yielded = False
        for identity in self.iter_identities():
            batch.append(identity)
            if len(batch) >= batch_size:
                yielded = True
                yield IdentityDiscoveryBatch(tuple(batch))
                batch = []
        if batch:
            yield IdentityDiscoveryBatch(tuple(batch), complete=True)
        elif not yielded:
            yield IdentityDiscoveryBatch((), complete=True)

    @property
    def supports_incremental_deletion_reconciliation(self) -> bool:
        """Whether incremental traversal is a complete snapshot of its window.

        Adapters may opt in when messages absent from the bounded refresh
        window are authoritative evidence of source deletion.
        """
        return False

    @property
    def incremental_refresh_lookback(self) -> timedelta:
        """Return the mutation-detection overlap used by incremental refreshes."""
        return timedelta(0)

    @abstractmethod
    def attachment_bytes(
        self,
        attachment: CanonicalAttachment,
    ) -> bytes:
        """
        Retrieve the binary contents of an attachment.

        The returned bytes must correspond to the attachment's SHA-256
        digest stored in the canonical model.
        """
        raise NotImplementedError

    def release_attachment_bytes(
        self,
        attachment: CanonicalAttachment,
    ) -> None:
        """Release any adapter-side attachment bytes retained for one message.

        Adapters may retain downloaded bytes between canonicalization and the
        importer requesting them. The importer calls this after each attachment
        regardless of whether the Archive already contained the asset.
        """
        del attachment
