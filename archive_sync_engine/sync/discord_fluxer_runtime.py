"""Application runtime for Discord-to-Fluxer synchronization.

This module owns only runtime composition and lifecycle.  Import, planning,
execution, and state persistence remain owned by their existing application
components.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from archive_sync_engine.operations import SyncOperation

from archive_sync_engine.adapters.exceptions import AdapterError
from archive_sync_engine.adapters.discord.runtime import (
    DiscordClientConfig,
    DiscordClientFactory,
    DiscordSourceRuntime,
)
from archive_sync_engine.adapters.fluxer import FluxerIdentityMapping
from archive_sync_engine.adapters.fluxer_runtime import (
    FluxerClientConfig,
    FluxerDestinationRuntime,
    FluxerHttpClientFactory,
)
from archive_sync_engine.archive.paths import ArchivePaths

from .pipeline import ArchiveSyncPipeline
from .runtime_request import SyncRuntimeRequest
from .state_namespace import destination_state_namespace


@dataclass(frozen=True, slots=True)
class DiscordFluxerSyncConfig:
    """Runtime configuration for one Discord-to-Fluxer synchronization."""

    discord: DiscordClientConfig
    fluxer: FluxerClientConfig
    fluxer_guild_id: str
    archive_paths: ArchivePaths
    identity_mappings: tuple[FluxerIdentityMapping, ...] = ()
    state_repository_path: str | None = None
    state_namespace: str = "default"
    incremental_lookback_days: float = 7

    def __post_init__(self) -> None:
        if not self.fluxer_guild_id:
            raise ValueError("Fluxer guild ID must not be empty.")


class DiscordFluxerSyncRuntime:
    """Own Discord/Fluxer clients and run one archive-mediated sync."""

    @classmethod
    def from_runtime_request(cls, request: SyncRuntimeRequest) -> "DiscordFluxerSyncRuntime":
        """Construct the concrete runtime from the generic registry request."""
        if request.input_adapter != "discord" or request.destination_adapter != "fluxer":
            raise AdapterError(
                "DiscordFluxerSyncRuntime requires the discord -> fluxer adapter pair."
            )
        try:
            discord = request.adapter_config["discord"]
            fluxer = request.adapter_config["fluxer"]
        except KeyError as exc:
            raise AdapterError(
                f"Missing runtime configuration for adapter {exc.args[0]!r}."
            ) from exc
        if not isinstance(discord, DiscordClientConfig):
            raise AdapterError("Runtime configuration for 'discord' is invalid.")
        if not isinstance(fluxer, FluxerClientConfig):
            raise AdapterError("Runtime configuration for 'fluxer' is invalid.")
        if len(request.destination_scope) != 1:
            raise AdapterError("Fluxer destination scope must contain exactly one server ID.")
        return cls(
            DiscordFluxerSyncConfig(
                discord=discord,
                fluxer=fluxer,
                fluxer_guild_id=request.destination_scope[0],
                archive_paths=ArchivePaths(request.archive_path),
                identity_mappings=tuple(request.adapter_config.get("identity_mappings", ())),
                state_namespace=destination_state_namespace(
                    request.destination_adapter,
                    request.destination_scope,
                ),
                incremental_lookback_days=float(request.adapter_config.get("incremental_lookback_days", 7)),
            )
        )

    def __init__(
        self,
        config: DiscordFluxerSyncConfig,
        *,
        discord_factory: DiscordClientFactory | None = None,
        fluxer_factory: FluxerHttpClientFactory | None = None,
        pipeline: ArchiveSyncPipeline | None = None,
    ) -> None:
        self._config = config
        self._closed = False
        self._discord_runtime: DiscordSourceRuntime | None = None
        self._fluxer_runtime: FluxerDestinationRuntime | None = None
        self._pipeline = pipeline or ArchiveSyncPipeline(
            archive_paths=config.archive_paths,
            state_repository_path=config.state_repository_path,
            state_namespace=config.state_namespace,
        )

        discord_factory = discord_factory or DiscordClientFactory()
        fluxer_factory = fluxer_factory or FluxerHttpClientFactory()

        try:
            discord_client = discord_factory.create(config.discord)
            self._discord_runtime = DiscordSourceRuntime(
                discord_client,
                guild_ids=config.discord.guild_ids,
                incremental_lookback_days=config.incremental_lookback_days,
            )
            self._fluxer_runtime = FluxerDestinationRuntime(
                guild_id=config.fluxer_guild_id,
                bot_client=config.fluxer,
                identity_mappings=config.identity_mappings,
                client_factory=fluxer_factory,
            )
        except Exception:
            if self._discord_runtime is not None:
                self._discord_runtime.close()
            if self._fluxer_runtime is not None:
                self._fluxer_runtime.close()
            raise

    @property
    def discord(self) -> DiscordSourceRuntime:
        """Return the owned Discord source runtime."""
        runtime = self._discord_runtime
        if runtime is None:
            raise AdapterError("Discord runtime is not available.")
        return runtime

    @property
    def fluxer(self) -> FluxerDestinationRuntime:
        """Return the owned Fluxer destination runtime."""
        runtime = self._fluxer_runtime
        if runtime is None:
            raise AdapterError("Fluxer runtime is not available.")
        return runtime

    def dry_run(self) -> tuple["SyncOperation", ...]:
        """Plan the current Archive-to-Fluxer synchronization without writes."""
        if self._closed:
            raise AdapterError(
                "Cannot dry-run a closed Discord-to-Fluxer runtime."
            )

        return self._pipeline.dry_run(
            destination=self.fluxer.adapter,
        )

    def set_incremental_refresh_lookback_days(self, days: int | float) -> None:
        """Set the Discord incremental refresh overlap for this sync run."""
        self.discord.adapter.set_incremental_refresh_lookback_days(days)

    def run(self, *, resume_import: bool = False) -> None:
        """Import Discord into the Archive, then synchronize the Archive to Fluxer."""
        if self._closed:
            raise AdapterError(
                "Cannot run a closed Discord-to-Fluxer runtime."
            )

        self._pipeline.run(
            source=self.discord.adapter,
            destination=self.fluxer.adapter,
            resume_import=resume_import,
        )

    def close(self) -> None:
        """Close both platform runtimes in reverse construction order."""
        if self._closed:
            return
        self._closed = True

        first_error: BaseException | None = None
        if self._fluxer_runtime is not None:
            try:
                self._fluxer_runtime.close()
            except BaseException as exc:
                first_error = exc

        if self._discord_runtime is not None:
            try:
                self._discord_runtime.close()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc

        if first_error is not None:
            raise first_error

    def __enter__(self) -> "DiscordFluxerSyncRuntime":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
