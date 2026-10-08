"""Durable, human-readable Archive state tags.

Tags are lightweight state markers, analogous to source-control tags.  They
identify an Archive state by sequence and record the source-import metadata
that was visible when the tag was created.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from archive_sync_engine.models._validation import require_timezone_aware


class ArchiveTagSourceStatus(str, Enum):
    """Status of the most recent source import represented by a tag."""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RUNNING = "running"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ArchiveTagSourceState:
    """Snapshot of source-import state visible when an Archive tag was made."""

    adapter: str
    scope: tuple[str, ...]
    session_id: str | None
    status: ArchiveTagSourceStatus
    started_at: datetime | None
    updated_at: datetime | None
    checkpoint: str | None
    error: str | None

    def __post_init__(self) -> None:
        if not self.adapter.strip():
            raise ValueError("source adapter cannot be empty.")
        if any(not value.strip() for value in self.scope):
            raise ValueError("source scope values cannot be empty.")
        for name, value in (
            ("started_at", self.started_at),
            ("updated_at", self.updated_at),
        ):
            if value is not None:
                require_timezone_aware(name, value)
        if self.started_at is not None and self.updated_at is not None:
            if self.updated_at < self.started_at:
                raise ValueError("updated_at cannot precede started_at.")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "adapter": self.adapter,
            "scope": list(self.scope),
            "session_id": self.session_id,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "checkpoint": self.checkpoint,
            "error": self.error,
        }

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> "ArchiveTagSourceState":
        scope = data.get("scope", [])
        if not isinstance(scope, list):
            raise ValueError("tag source scope must be a JSON array.")

        def parse_datetime(key: str) -> datetime | None:
            value = data.get(key)
            if value is None:
                return None
            if not isinstance(value, str):
                raise TypeError(f"tag source {key} must be a string or null.")
            return datetime.fromisoformat(value)

        return cls(
            adapter=str(data["adapter"]),
            scope=tuple(str(value) for value in scope),
            session_id=(str(data["session_id"]) if data.get("session_id") is not None else None),
            status=ArchiveTagSourceStatus(str(data.get("status", "unknown"))),
            started_at=parse_datetime("started_at"),
            updated_at=parse_datetime("updated_at"),
            checkpoint=(str(data["checkpoint"]) if data.get("checkpoint") is not None else None),
            error=(str(data["error"]) if data.get("error") is not None else None),
        )


@dataclass(frozen=True, slots=True)
class ArchiveTag:
    """A named, immutable marker for an Archive state."""

    id: str
    name: str
    sequence: int
    created_at: datetime
    source: ArchiveTagSourceState | None = None
    archive_database_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("tag id cannot be empty.")
        if not self.name.strip():
            raise ValueError("tag name cannot be empty.")
        if self.sequence < 1:
            raise ValueError("tag sequence must be >= 1.")
        require_timezone_aware("created_at", self.created_at)
        if self.archive_database_sha256 is not None:
            if len(self.archive_database_sha256) != 64 or any(
                character not in "0123456789abcdef"
                for character in self.archive_database_sha256.lower()
            ):
                raise ValueError("archive_database_sha256 must be a SHA-256 hex digest.")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "sequence": self.sequence,
            "created_at": self.created_at.isoformat(),
            "source": self.source.to_json_dict() if self.source else None,
            "archive_database_sha256": self.archive_database_sha256,
        }

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> "ArchiveTag":
        raw_source = data.get("source")
        if raw_source is not None and not isinstance(raw_source, Mapping):
            raise TypeError("tag source must be an object or null.")
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            sequence=int(data["sequence"]),
            created_at=datetime.fromisoformat(str(data["created_at"])),
            source=(
                ArchiveTagSourceState.from_json_dict(raw_source)
                if raw_source is not None
                else None
            ),
            archive_database_sha256=(
                str(data["archive_database_sha256"])
                if data.get("archive_database_sha256") is not None
                else None
            ),
        )


class ArchiveTagRegistry:
    """Persistent registry for Archive tags."""

    FORMAT_VERSION = 1

    def __init__(self, path: Path) -> None:
        self._path = path

    def create(
        self,
        name: str,
        *,
        created_at: datetime,
        source: ArchiveTagSourceState | None = None,
        archive_database_sha256: str | None = None,
    ) -> ArchiveTag:
        """Create a new named tag at the current end of the tag sequence."""
        normalized = name.strip()
        if not normalized:
            raise ValueError("tag name cannot be empty.")

        tags = list(self.iter_tags())
        if any(tag.name == normalized for tag in tags):
            raise ValueError(f"Archive tag already exists: {normalized!r}")

        sequence = max((tag.sequence for tag in tags), default=0) + 1
        tag = ArchiveTag(
            id=f"tag-{uuid4()}",
            name=normalized,
            sequence=sequence,
            created_at=created_at,
            source=source,
            archive_database_sha256=archive_database_sha256,
        )
        tags.append(tag)
        self._write(tags)
        return tag

    def get(self, name_or_id: str) -> ArchiveTag | None:
        """Return a tag by human-readable name or opaque tag ID."""
        needle = name_or_id.strip()
        if not needle:
            return None
        for tag in self.iter_tags():
            if tag.name == needle or tag.id == needle:
                return tag
        return None

    def require(self, name_or_id: str) -> ArchiveTag:
        tag = self.get(name_or_id)
        if tag is None:
            raise KeyError(f"Archive tag not found: {name_or_id!r}")
        return tag

    def iter_tags(self) -> Iterable[ArchiveTag]:
        """Iterate tags in creation sequence order."""
        if not self._path.is_file():
            return ()
        with self._path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, Mapping):
            raise ValueError("Archive tags must contain a JSON object.")
        if int(data.get("format_version", self.FORMAT_VERSION)) != self.FORMAT_VERSION:
            raise ValueError("Unsupported Archive tag format version.")
        raw_tags = data.get("tags", [])
        if not isinstance(raw_tags, list):
            raise ValueError("Archive tags must contain a JSON array.")
        tags = [ArchiveTag.from_json_dict(value) for value in raw_tags]
        tags.sort(key=lambda tag: tag.sequence)
        return tuple(tags)

    def between(
        self,
        start: str,
        end: str,
        *,
        inclusive: bool = False,
    ) -> tuple[ArchiveTag, ...]:
        """Return tags ordered between two named/ID tag boundaries."""
        first = self.require(start)
        last = self.require(end)
        if first.sequence > last.sequence:
            raise ValueError("start tag must not follow end tag.")
        tags = tuple(self.iter_tags())
        if inclusive:
            return tuple(tag for tag in tags if first.sequence <= tag.sequence <= last.sequence)
        return tuple(tag for tag in tags if first.sequence < tag.sequence < last.sequence)

    def _write(self, tags: list[ArchiveTag]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": self.FORMAT_VERSION,
            "tags": [tag.to_json_dict() for tag in sorted(tags, key=lambda tag: tag.sequence)],
        }
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(self._path)
