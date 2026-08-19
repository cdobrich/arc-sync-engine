from __future__ import annotations

import json
from typing import Mapping

from datetime import datetime
from datetime import timezone
from pathlib import Path

from .manifest import ArchiveManifest
from .paths import ArchivePaths
from .version import ARCHIVE_ENGINE_VERSION
from archive_sync_engine.adapters.source import SourceRefreshCursor


class ArchivePackage:
    """
    Represents an Archive Package on disk.

    The package currently consists of:

    - manifest.json
    - archive.sqlite
    - attachments/
    """

    @classmethod
    def initialize(
        cls,
        paths: ArchivePaths,
    ) -> "ArchivePackage":
        """Create a new, empty Archive Package without overwriting data."""
        root = paths.root.expanduser()
        if root.exists() and any(root.iterdir()):
            raise FileExistsError(
                f"Archive Package target is not empty: {root}"
            )

        paths = ArchivePaths(root=root)
        paths.ensure_exists()

        from archive_sync_engine.archive.store import ArchiveStore

        store = ArchiveStore.create(paths)
        store.close()

        package = cls(paths)
        package.save_manifest(package.create_manifest())
        return package

    def __init__(
        self,
        paths: ArchivePaths,
    ) -> None:
        from archive_sync_engine.asset_store import AssetStore

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
    def asset_store(
        self,
    ) -> AssetStore:
        """Return the package-owned content-addressed asset store."""

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
    # Run configuration
    #

    def save_run_configuration(
        self,
        configuration: "SyncRunConfiguration",
    ) -> None:
        """Persist non-secret configuration identifying the current run."""

        with self._paths.run_configuration.open(
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                configuration.to_json_dict(),
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")

    def load_run_configuration(
        self,
    ) -> SyncRunConfiguration:
        """Load persisted non-secret run configuration."""

        with self._paths.run_configuration.open(
            "r",
            encoding="utf-8",
        ) as handle:
            data = json.load(handle)

        if not isinstance(data, dict):
            raise ValueError("Run configuration must contain a JSON object.")
        from archive_sync_engine.sync.run_configuration import SyncRunConfiguration
        return SyncRunConfiguration.from_json_dict(data)

    #
    # Session
    #

    def save_session(
        self,
        session: "SyncSession",
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
        state: "ImportState",
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

    def save_import_cursors(
        self,
        cursors: "Mapping[str, SourceRefreshCursor]",
    ) -> None:
        """Persist source-aware incremental refresh cursors."""
        with self._paths.import_cursors.open("w", encoding="utf-8") as handle:
            json.dump(
                {key: cursor.to_json_dict() for key, cursor in sorted(cursors.items())},
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")

    def load_import_cursors(self) -> dict[str, "SourceRefreshCursor"]:
        """Load source-aware incremental refresh cursors."""
        with self._paths.import_cursors.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("Import cursors must contain a JSON object.")
        from archive_sync_engine.adapters.source import SourceRefreshCursor
        return {
            str(key): SourceRefreshCursor.from_json_dict(value)
            for key, value in data.items()
        }
