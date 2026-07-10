"""
Canonical archive.

The Archive stores the engine's canonical representation of imported data.

It is the boundary between acquisition and synchronization.

Importers populate the Archive.

Planners read from the Archive.

The Archive contains no platform-specific logic.
"""

from .archive import Archive

__all__ = [
    "Archive",
]
