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
from dataclasses import dataclass
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

    def iter_identities_since(
        self,
        cursors: Mapping[str, SourceRefreshCursor],
    ) -> Iterable[CanonicalIdentity]:
        """Enumerate identities relevant to an incremental refresh.

        Adapters without an optimized identity traversal safely fall back to
        their complete identity enumeration.
        """
        yield from self.iter_identities()

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
