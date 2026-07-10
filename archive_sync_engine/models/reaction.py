"""
Canonical reaction model.

A CanonicalReaction represents a single participant reacting to a message.

The canonical model intentionally represents one reaction event rather than
an aggregated reaction count. This preserves the complete reaction state and
allows destination adapters to aggregate reactions if required.

Reaction identity is defined by the tuple:

    (identity_key, emoji, emoji_id)

No separate reaction identifier exists because most supported platforms do
not expose one.
"""

from __future__ import annotations
from dataclasses import dataclass
from .ids import EmojiId, IdentityKey


@dataclass(frozen=True, slots=True)
class CanonicalReaction:
    """
    Represents a single user's reaction to a message.
    """

    identity_key: IdentityKey
    emoji: str
    emoji_id: EmojiId | None = None
    is_custom: bool = False

    def __post_init__(self) -> None:
        """
        Validate canonical reaction invariants.
        """

        if not self.emoji:
            raise ValueError("emoji must not be empty")

        if self.is_custom and self.emoji_id is None:
            raise ValueError(
                "Custom emoji reactions require an emoji_id."
            )

        # If an emoji is a standard Unicode emoji, it cannot have a custom database ID.
        if not self.is_custom and self.emoji_id is not None:
            raise ValueError(
                "Unicode emoji reactions must not specify an emoji_id."
            )
