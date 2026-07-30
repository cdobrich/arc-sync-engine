from __future__ import annotations

import json

from datetime import datetime
from datetime import timezone

from .manifest import ArchiveManifest
from .paths import ArchivePaths
from .version import ARCHIVE_ENGINE_VERSION


class ArchivePackage:
    """
    Represents an Archive Package on disk.

    The package currently consists of:

    - manifest.json
    - archive.sqlite
    - attachments/
    """

    def __init__(
        self,
        paths: ArchivePaths,
    ) -> None:

        self._paths = paths

    @property
    def paths(
        self,
    ) -> ArchivePaths:
        """
        Filesystem layout of this package.
        """

        return self._paths

    def load_manifest(
        self,
    ) -> ArchiveManifest:
        """
        Load the Archive Package manifest.
        """

        with self._paths.manifest.open(
            "r",
            encoding="utf-8",
        ) as fp:

            data = json.load(fp)

        return ArchiveManifest.from_json_dict(
            data,
        )

    def save_manifest(
        self,
        manifest: ArchiveManifest,
    ) -> None:
        """
        Save the Archive Package manifest.
        """

        with self._paths.manifest.open(
            "w",
            encoding="utf-8",
        ) as fp:

            json.dump(
                manifest.to_json_dict(),
                fp,
                indent=4,
                sort_keys=True,
            )

            fp.write(
                "\n"
            )

    def create_manifest(
        self,
    ) -> ArchiveManifest:
        """
        Construct a manifest describing this Archive Package.
        """

        return ArchiveManifest(
            archive_engine_version=
                ARCHIVE_ENGINE_VERSION,

            created_at=datetime.now(
                timezone.utc,
            ),
        )