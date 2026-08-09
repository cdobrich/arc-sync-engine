"""
Destination platform capability definitions.

Destination capabilities describe the features supported by a destination
platform. They are used by the Planner to generate synchronization plans
that are compatible with the destination.

Capabilities describe what a platform is capable of, not what it currently
contains.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DestinationCapabilities:
    """
    Immutable description of destination platform capabilities.

    These capabilities allow the Planner to adapt synchronization
    behavior without requiring knowledge of any specific platform.
    """

    supports_threads: bool = False
    supports_message_editing: bool = True
    supports_message_deletion: bool = True
    supports_conversation_deletion: bool = True
    supports_message_pinning: bool = True
    supports_reactions: bool = True
    supports_custom_emoji: bool = True
    supports_attachments: bool = True
    supports_attachment_reordering: bool = False
    supports_replying: bool = True
    supports_identity_updates: bool = False