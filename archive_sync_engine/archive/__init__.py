"""
Canonical archive.

The Archive stores the engine's canonical representation of imported data.

It is the boundary between acquisition and synchronization.

Archive Writers populate the Archive.

Planners read from the Archive.

The Archive contains no platform-specific logic.
"""

from .archive import Archive
from .manifest import ArchiveManifest
from .paths import ArchivePaths
from .writer import ArchiveWriter
from .integrity import ArchiveIntegrityReport, validate_archive_package

__all__ = [
    "Archive",
    "ArchiveManifest",
    "ArchivePaths",
    "ArchiveWriter",
    "ArchiveIntegrityReport",
    "validate_archive_package",
]
