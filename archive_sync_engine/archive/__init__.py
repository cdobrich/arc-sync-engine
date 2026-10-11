"""
Canonical archive.

The Archive stores the engine's canonical representation of imported data.

It is the boundary between acquisition and synchronization.

Archive Writers populate the Archive.

Planners read from the Archive.

The Archive contains no platform-specific logic.
"""

from .archive import Archive
from .package import ArchivePackage
from .manifest import ArchiveManifest
from .tags import ArchiveTag, ArchiveTagRegistry, ArchiveTagSourceState, ArchiveTagSourceStatus
from .paths import ArchivePaths
from .writer import ArchiveWriter
from .integrity import ArchiveIntegrityReport, validate_archive_package

__all__ = [
    "Archive",
    "ArchivePackage",
    "ArchiveManifest",
    "ArchiveTag",
    "ArchiveTagRegistry",
    "ArchiveTagSourceState",
    "ArchiveTagSourceStatus",
    "ArchivePaths",
    "ArchiveWriter",
    "ArchiveIntegrityReport",
    "validate_archive_package",
]
