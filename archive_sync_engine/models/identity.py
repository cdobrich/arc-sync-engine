"""
Canonical identity model.

A CanonicalIdentity represents a logical participant in a conversation.
It intentionally contains no platform-specific identifiers. Those are
resolved by adapters and stored within the Archive's identity mappings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from .ids import IdentityKey


@dataclass(frozen=True, slots=True)
class CanonicalIdentity:
    """
    Represents a single logical identity.

    identity_key is the engine's stable identifier for the participant.

    display_name is the preferred human-readable name.

    metadata is reserved for optional adapter-specific information that
    should be preserved but is not interpreted by the engine.
    """

    identity_key: IdentityKey

    display_name: str

    avatar_url: str | None = None

    is_bot: bool = False

    metadata: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        """
        Ensure metadata is immutable regardless of the caller.
        """
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )
