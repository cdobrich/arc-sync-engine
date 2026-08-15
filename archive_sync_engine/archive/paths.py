"""
Filesystem layout for an Archive Package.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ArchivePaths:
    """
    Describes the filesystem layout of an Archive Package.

    An Archive Package is a portable directory containing:

        archive.sqlite
        manifest.json
        attachments/

    This class defines only the filesystem layout. It contains no
    database, serialization, or archive logic.
    """

    root: Path

    @property
    def database(self) -> Path:
        """
        Path to the archive SQLite database.
        """
        return self.root / "archive.sqlite"

    @property
    def attachments(self) -> Path:
        """
        Directory containing attachment content.
        """
        return self.root / "attachments"

    @property
    def manifest(self) -> Path:
        """
        Path to the archive manifest.
        """
        return self.root / "manifest.json"

    def attachment_path(
        self,
        sha256: str,
    ) -> Path:
        """
        Return the storage path for an attachment using SHA-256
        content-addressed storage.

        Layout:

            attachments/
                ab/
                    abcdef1234...
        """

        prefix = sha256[:2]

        return (
            self.attachments
            / prefix
            / sha256
        )

    def ensure_exists(self) -> None:
        """
        Create the Archive Package directory structure if required.

        This creates only the top-level package structure. Attachment
        shard directories are created lazily as attachments are written.
        """

        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.attachments.mkdir(
            parents=True,
            exist_ok=True,
        )

    @property
    def run_configuration(self) -> Path:
        """Path to the persisted, non-secret run configuration."""
        return self.root / "run.json"

    @property
    def session(self) -> Path:
        """
        Path to the synchronization session.
        """
        return self.root / "session.json"


    @property
    def import_state(self) -> Path:
        return self.root / "import-state.json"