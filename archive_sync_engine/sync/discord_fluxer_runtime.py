"""Application runtime for Discord-to-Fluxer synchronization.

This module owns only runtime composition and lifecycle.  Import, planning,
execution, and state persistence remain owned by their existing application
components.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True, slots=True)
class DiscordFluxerSyncConfig:
    """Runtime configuration for one Discord-to-Fluxer synchronization."""

    discord: DiscordClientConfig
    fluxer: FluxerClientConfig
    fluxer_guild_id: str
    archive_paths: ArchivePaths
    identity_mappings: tuple[FluxerIdentityMapping, ...] = ()

    def __post_init__(self) -> None:
        if not self.fluxer_guild_id:
            raise ValueError("Fluxer guild ID must not be empty.")


class DiscordFluxerSyncRuntime:
    """Own Discord/Fluxer clients and run one archive-mediated sync."""

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
        )

        discord_factory = discord_factory or DiscordClientFactory()
        fluxer_factory = fluxer_factory or FluxerHttpClientFactory()

        try:
            discord_client = discord_factory.create(config.discord)
            self._discord_runtime = DiscordSourceRuntime(
                discord_client,
                guild_ids=config.discord.guild_ids,
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
