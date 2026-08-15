from __future__ import annotations

import json

from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .manifest import ArchiveManifest
from .paths import ArchivePaths
from .version import ARCHIVE_ENGINE_VERSION
from .store import ArchiveStore

from archive_sync_engine.asset_store import AssetStore

if TYPE_CHECKING:
    from archive_sync_engine.sync.session import SyncSession
    from archive_sync_engine.importer.state import ImportState

class ArchivePackage:
    """Represents an Archive Package on disk."""

    @classmethod
    def initialize(cls, paths: ArchivePaths) -> "ArchivePackage":
        """Create a new, empty Archive Package at ``paths``.

        Initialization creates the canonical SQLite database, package
        directories, and manifest. Existing files are never overwritten.
        A non-empty target directory is rejected so a partially initialized
        or unrelated project cannot be mistaken for a new Archive Package.
        """
        root = paths.root.expanduser()
        if root.exists() and any(root.iterdir()):
            raise FileExistsError(
                f"Archive Package target is not empty: {root}"
            )

        paths = ArchivePaths(root=root)
        paths.ensure_exists()

        store = ArchiveStore.create(paths)
        store.close()

        package = cls(paths)
        package.save_manifest(package.create_manifest())
        return package

    def __init__(
        self,
        paths: ArchivePaths,
    ) -> None:
        self._asset_store = AssetStore(
            paths.root,
        )
        self._paths = paths

    @property
    def asset_store(
            self,
    ) -> AssetStore:
        """
        Return the AssetStore owned by this Archive Package.
        """

        return self._asset_store

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

    #
    # Session
    #

    def save_session(
        self,
        session: SyncSession,
    ) -> None:
        """
        Persist the current synchronization session.

        Session state is operational metadata and is stored separately
        from the canonical archive database.
        """

        with self._paths.session.open(
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                session.to_json_dict(),
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")


    def load_session(
        self,
    ) -> SyncSession:
        """
        Load the persisted synchronization session.

        Raises FileNotFoundError if the Archive Package does not contain
        a session file.
        """

        with self._paths.session.open(
            "r",
            encoding="utf-8",
        ) as handle:
            data = json.load(handle)

        if not isinstance(data, dict):
            raise ValueError("Archive session must contain a JSON object.")

        from archive_sync_engine.sync.session import SyncSession

        return SyncSession.from_json_dict(
            data,
        )

    #
    # State
    #

    def save_import_state(
        self,
        state: ImportState,
    ) -> None:
        """
        Persist opaque importer-owned state.
        """

        with self._paths.import_state.open(
            "w",
            encoding="utf-8",
        ) as handle:

            json.dump(
                dict(state.payload),
                handle,
                indent=2,
                sort_keys=True,
            )

            handle.write(
                "\n",
            )

    def load_import_state(
        self,
    ) -> ImportState:
        """
        Load persisted importer-owned state.

        Raises FileNotFoundError when no import state has been persisted.
        """

        with self._paths.import_state.open(
            "r",
            encoding="utf-8",
        ) as handle:

            data = json.load(
                handle,
            )

        if not isinstance(
            data,
            dict,
        ):
            raise ValueError(
                "Import state must contain a JSON object."
            )

        from archive_sync_engine.importer.state import ImportState

        return ImportState(
            payload=data,
        )