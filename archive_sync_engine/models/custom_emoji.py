"""Canonical custom emoji model."""
from __future__ import annotations
from dataclasses import dataclass
from .ids import EmojiId

@dataclass(frozen=True, slots=True)
class CanonicalCustomEmoji:
    """A custom emoji and its content-addressed archived asset."""
    id: EmojiId
    name: str
    animated: bool
    content_type: str | None
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if not str(self.id):
            raise ValueError("custom emoji id must not be empty")
        if not self.name:
            raise ValueError("custom emoji name must not be empty")
        if self.size < 0:
            raise ValueError("custom emoji size must not be negative")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256.lower()):
            raise ValueError("custom emoji sha256 must be a 64-character hexadecimal digest")
