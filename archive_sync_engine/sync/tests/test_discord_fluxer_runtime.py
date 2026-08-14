from __future__ import annotations

from unittest.mock import Mock

import pytest

from archive_sync_engine.adapters.discord.runtime import DiscordClientConfig
from archive_sync_engine.adapters.fluxer import FluxerIdentityMapping
from archive_sync_engine.adapters.fluxer_runtime import FluxerClientConfig
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.sync.discord_fluxer_runtime import (
    DiscordFluxerSyncConfig,
    DiscordFluxerSyncRuntime,
)


class FakeDiscordClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeFluxerHttpClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeDiscordFactory:
    def __init__(self) -> None:
        self.client = FakeDiscordClient()
        self.configs: list[DiscordClientConfig] = []

    def create(self, config: DiscordClientConfig):
        self.configs.append(config)
        return self.client


class FakeFluxerFactory:
    def __init__(self) -> None:
        self.clients: list[FakeFluxerHttpClient] = []
        self.configs: list[FluxerClientConfig] = []

    def create(self, config: FluxerClientConfig):
        self.configs.append(config)
        client = FakeFluxerHttpClient()
        self.clients.append(client)
        return client


def _config(tmp_path) -> DiscordFluxerSyncConfig:
    return DiscordFluxerSyncConfig(
        discord=DiscordClientConfig(
            token="discord-token",
            guild_ids=(1,),
        ),
        fluxer=FluxerClientConfig(
            token="fluxer-bot-token",
            is_bot=True,
        ),
        fluxer_guild_id="fluxer-guild-1",
        archive_paths=ArchivePaths(tmp_path / "archive"),
        identity_mappings=(
            FluxerIdentityMapping("identity-1", "user-token"),
        ),
    )


def test_runtime_runs_archive_mediated_discord_to_fluxer_pipeline(tmp_path) -> None:
    discord_factory = FakeDiscordFactory()
    fluxer_factory = FakeFluxerFactory()
    pipeline = Mock()

    runtime = DiscordFluxerSyncRuntime(
        _config(tmp_path),
        discord_factory=discord_factory,
        fluxer_factory=fluxer_factory,
        pipeline=pipeline,
    )

    runtime.run(resume_import=True)

    pipeline.run.assert_called_once_with(
        source=runtime.discord.adapter,
        destination=runtime.fluxer.adapter,
        resume_import=True,
    )


def test_runtime_closes_destination_and_source_runtimes(tmp_path) -> None:
    discord_factory = FakeDiscordFactory()
    fluxer_factory = FakeFluxerFactory()

    runtime = DiscordFluxerSyncRuntime(
        _config(tmp_path),
        discord_factory=discord_factory,
        fluxer_factory=fluxer_factory,
        pipeline=Mock(),
    )

    runtime.close()

    assert discord_factory.client.closed is True
    assert fluxer_factory.clients[0].closed is True


def test_fluxer_client_construction_failure_closes_discord_runtime(
    tmp_path,
) -> None:
    discord_factory = FakeDiscordFactory()

    class FailingFluxerFactory:
        def create(self, config: FluxerClientConfig):
            raise RuntimeError("Fluxer unavailable")

    with pytest.raises(RuntimeError, match="Fluxer unavailable"):
        DiscordFluxerSyncRuntime(
            _config(tmp_path),
            discord_factory=discord_factory,
            fluxer_factory=FailingFluxerFactory(),
            pipeline=Mock(),
        )

    assert discord_factory.client.closed is True
