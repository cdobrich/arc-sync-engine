from __future__ import annotations

import json
from typing import TYPE_CHECKING, Mapping

from datetime import datetime
from datetime import timezone
import hashlib
from pathlib import Path

from .manifest import ArchiveManifest
from .paths import ArchivePaths
from .version import ARCHIVE_ENGINE_VERSION
from .tags import ArchiveTag, ArchiveTagRegistry, ArchiveTagSourceState
from ..asset_store import AssetStore

if TYPE_CHECKING:
    from ..sync import SyncSession
    from ..sync.run_configuration import SyncRunConfiguration
    from ..importer import ImportState


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
    # Archive tags
    #

    def create_tag(
        self,
        name: str,
        *,
        created_at: datetime | None = None,
    ) -> ArchiveTag:
        """Create an immutable human-readable tag for the current Archive state."""
        now = created_at or datetime.now(timezone.utc)
        try:
            source = self.load_last_import_source_state()
        except FileNotFoundError:
            source = self._current_import_tag_source()
        return ArchiveTagRegistry(self._paths.tags).create(
            name,
            created_at=now,
            source=source,
            archive_database_sha256=self._archive_database_sha256(),
        )

    def rename_tag(self, name_or_id: str, new_name: str) -> ArchiveTag:
        """Rename an active Archive tag while preserving its identity."""
        return ArchiveTagRegistry(self._paths.tags).rename(name_or_id, new_name)

    def delete_tag(
        self,
        name_or_id: str,
        *,
        deleted_at: datetime | None = None,
    ) -> ArchiveTag:
        """Tombstone an Archive tag without removing its historical identity."""
        return ArchiveTagRegistry(self._paths.tags).delete(
            name_or_id,
            deleted_at=deleted_at or datetime.now(timezone.utc),
        )

    def tag_matches_current_database(self, name_or_id: str) -> bool:
        """Return whether a tag's recorded SQLite fingerprint matches now."""
        tag = self.require_tag(name_or_id)
        if tag.archive_database_sha256 is None:
            return False
        return tag.archive_database_sha256 == self._archive_database_sha256()

    def get_tag(self, name_or_id: str) -> ArchiveTag | None:
        """Return an Archive tag by name or opaque tag ID."""
        return ArchiveTagRegistry(self._paths.tags).get(name_or_id)

    def require_tag(self, name_or_id: str) -> ArchiveTag:
        """Return an Archive tag or raise KeyError when it does not exist."""
        return ArchiveTagRegistry(self._paths.tags).require(name_or_id)

    def iter_tags(self):
        """Iterate Archive tags in creation sequence order."""
        return ArchiveTagRegistry(self._paths.tags).iter_tags()

    def tags_between(
        self,
        start: str,
        end: str,
        *,
        inclusive: bool = False,
    ) -> tuple[ArchiveTag, ...]:
        """Return named state markers between two tag boundaries."""
        return ArchiveTagRegistry(self._paths.tags).between(
            start,
            end,
            inclusive=inclusive,
        )

    def save_last_import_source_state(
        self,
        source: ArchiveTagSourceState,
    ) -> None:
        """Persist the most recent source-import state independently of the active session."""
        with self._paths.last_import.open("w", encoding="utf-8") as handle:
            json.dump(source.to_json_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")

    def load_last_import_source_state(self) -> ArchiveTagSourceState:
        """Load the most recent durable source-import state."""
        with self._paths.last_import.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("Last import state must contain a JSON object.")
        return ArchiveTagSourceState.from_json_dict(data)

    def snapshot_import_source_state(self) -> ArchiveTagSourceState | None:
        """Build source-import metadata from the persisted import session/configuration."""
        return self._current_import_tag_source()

    def _archive_database_sha256(self) -> str | None:
        """Return a storage-state fingerprint for the current SQLite database."""
        if not self._paths.database.is_file():
            return None
        digest = hashlib.sha256()
        with self._paths.database.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _current_import_tag_source(self) -> ArchiveTagSourceState | None:
        """Snapshot the persisted import session/configuration for a new tag."""
        try:
            session = self.load_session()
            configuration = self.load_run_configuration()
        except FileNotFoundError:
            return None

        from archive_sync_engine.sync.run_configuration import RunDirection

        if configuration.direction is not RunDirection.IMPORT or session.direction.value != "import":
            return None

        from .tags import ArchiveTagSourceStatus

        if session.completed:
            status = ArchiveTagSourceStatus.COMPLETED
        elif session.cancelled:
            status = ArchiveTagSourceStatus.CANCELLED
        elif session.error:
            status = ArchiveTagSourceStatus.FAILED
        else:
            status = ArchiveTagSourceStatus.RUNNING

        return ArchiveTagSourceState(
            adapter=configuration.input_adapter,
            scope=configuration.input_scope,
            session_id=session.id,
            status=status,
            started_at=session.started_at,
            updated_at=session.updated_at,
            checkpoint=session.checkpoint,
            error=session.error,
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

    def save_discovery_state(
        self,
        state: "DiscoveryState",
    ) -> None:
        """Persist the durable source-discovery lifecycle checkpoint."""
        with self._paths.discovery_state.open("w", encoding="utf-8") as handle:
            json.dump(
                state.to_json_dict(),
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")

    def load_discovery_state(
        self,
    ) -> "DiscoveryState":
        """Load the durable source-discovery lifecycle checkpoint."""
        with self._paths.discovery_state.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        from archive_sync_engine.importer.discovery_state import DiscoveryState
        return DiscoveryState.from_json_dict(data)

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

    def save_import_recovery_cursors(
        self,
        cursors: "Mapping[str, SourceRefreshCursor]",
    ) -> None:
        """Persist full-import recovery cursors separately from refresh cursors."""
        with self._paths.import_recovery_cursors.open("w", encoding="utf-8") as handle:
            json.dump(
                {key: cursor.to_json_dict() for key, cursor in sorted(cursors.items())},
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")

    def load_import_recovery_cursors(self) -> dict[str, "SourceRefreshCursor"]:
        """Load full-import recovery cursors."""
        with self._paths.import_recovery_cursors.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("Import recovery cursors must contain a JSON object.")
        from archive_sync_engine.adapters.source import SourceRefreshCursor
        return {
            str(key): SourceRefreshCursor.from_json_dict(value)
            for key, value in data.items()
        }

    def clear_import_recovery_cursors(self) -> None:
        """Remove completed full-import recovery cursors."""
        try:
            self._paths.import_recovery_cursors.unlink()
        except FileNotFoundError:
            pass

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
