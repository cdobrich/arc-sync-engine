from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from archive_sync_engine.adapters import AdapterError
from archive_sync_engine.adapters.discord import (
    DiscordClientConfig,
    DiscordClientFactory,
    DiscordSourceRuntime,
)
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.importer.canonical_coordinator import ImportReport


def test_discord_client_factory_normalizes_guild_ids_and_authenticates() -> None:
    calls: list[object] = []

    class FakeClient:
        def __init__(self, *, intents: object) -> None:
            self.intents = intents

        async def login(self, token: str) -> None:
            calls.append(("login", token))

        async def close(self) -> None:
            calls.append(("close",))

    class FakeIntents:
        def __init__(self) -> None:
            self.guilds = False
            self.members = False
            self.message_content = False

        @classmethod
        def none(cls) -> "FakeIntents":
            return cls()

    fake_module = SimpleNamespace(
        Client=FakeClient,
        Intents=FakeIntents,
    )

    factory = DiscordClientFactory(importer=lambda: fake_module)
    config = DiscordClientConfig(
        token="discord-token",
        guild_ids=(2, 1, 2),
    )

    client = factory.create(config)

    assert isinstance(client, FakeClient)
    assert config.guild_ids == (1, 2)
    assert calls == [("login", "discord-token")]



def test_discord_client_factory_uses_supplied_runner_for_login() -> None:
    calls: list[object] = []

    class FakeClient:
        def __init__(self, *, intents: object) -> None:
            self.intents = intents

        async def login(self, token: str) -> None:
            calls.append(("login", token))

    class FakeIntents:
        @classmethod
        def none(cls) -> "FakeIntents":
            return cls()

    fake_module = SimpleNamespace(Client=FakeClient, Intents=FakeIntents)

    import asyncio

    loop = asyncio.new_event_loop()
    try:
        factory = DiscordClientFactory(importer=lambda: fake_module)
        factory.create(
            DiscordClientConfig(token="discord-token", guild_ids=(1,)),
            runner=loop.run_until_complete,
        )
    finally:
        loop.close()

    assert calls == [("login", "discord-token")]


def test_discord_source_adapter_can_reuse_runtime_owned_event_loop() -> None:
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        class FakeClient:
            async def close(self) -> None:
                pass

        from archive_sync_engine.adapters.discord.source import DiscordSourceAdapter

        adapter = DiscordSourceAdapter(FakeClient(), (1,))
        adapter.set_runner(loop.run_until_complete)

        async def identify() -> str:
            return "same-loop"

        assert adapter._run(identify()) == "same-loop"
    finally:
        loop.close()

def test_discord_client_factory_wraps_client_construction_failure() -> None:
    class FakeIntents:
        def __init__(self) -> None:
            self.guilds = False
            self.members = False
            self.message_content = False

        @classmethod
        def none(cls) -> "FakeIntents":
            return cls()

    fake_module = SimpleNamespace(
        Intents=FakeIntents,
    )

    factory = DiscordClientFactory(importer=lambda: fake_module)

    with pytest.raises(AdapterError, match="Client"):
        factory.create(
            DiscordClientConfig(
                token="discord-token",
                guild_ids=(1,),
            )
        )


def test_discord_source_runtime_closes_client_once() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1

        def get_guild(self, guild_id: int) -> None:
            return None

    client = FakeClient()
    runtime = DiscordSourceRuntime(client, guild_ids=(1,))

    runtime.close()
    runtime.close()

    assert client.close_calls == 1


def test_discord_source_runtime_exposes_canonical_adapter() -> None:
    class FakeClient:
        async def close(self) -> None:
            pass

    runtime = DiscordSourceRuntime(FakeClient(), guild_ids=(1,))

    assert runtime.adapter.name == "Discord"
    assert runtime.input_scope == ("1",)


def test_discord_source_runtime_imports_through_canonical_coordinator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeCoordinator:
        def __init__(self, paths: ArchivePaths) -> None:
            captured["paths"] = paths

        def run(self, source, *, resume: bool = False) -> None:
            captured["source"] = source
            captured["resume"] = resume

    monkeypatch.setattr(
        "archive_sync_engine.adapters.discord.runtime.CanonicalImportCoordinator",
        FakeCoordinator,
    )

    class FakeClient:
        async def close(self) -> None:
            pass

    runtime = DiscordSourceRuntime(FakeClient(), guild_ids=(1,))
    paths = ArchivePaths(tmp_path / "archive")

    runtime.import_to_archive(paths, resume=True)

    assert captured["paths"] == paths
    assert captured["source"] is runtime.adapter
    assert captured["resume"] is True


def test_discord_source_runtime_propagates_import_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = ImportReport("import-test", 1, 2, 3, 4)

    class FakeCoordinator:
        def __init__(self, paths: ArchivePaths) -> None:
            pass

        def run(self, source, *, resume: bool = False) -> ImportReport:
            return report

    monkeypatch.setattr(
        "archive_sync_engine.adapters.discord.runtime.CanonicalImportCoordinator",
        FakeCoordinator,
    )

    class FakeClient:
        async def close(self) -> None:
            pass

    runtime = DiscordSourceRuntime(FakeClient(), guild_ids=(1,))

    assert runtime.import_to_archive(ArchivePaths(tmp_path / "archive")) is report


def test_discord_source_runtime_can_import_empty_scope_into_archive(
    tmp_path: Path,
) -> None:
    class FakeGuild:
        members: list[object] = []
        channels: list[object] = []
        threads: list[object] = []

    class FakeClient:
        def get_guild(self, guild_id: int) -> FakeGuild:
            return FakeGuild()

        async def fetch_guild(self, guild_id: int) -> FakeGuild:
            return FakeGuild()

        async def close(self) -> None:
            pass

    paths = ArchivePaths(tmp_path / "archive")
    runtime = DiscordSourceRuntime(FakeClient(), guild_ids=(1,))

    runtime.import_to_archive(paths)

    assert paths.database.exists()
    assert paths.session.exists()


def test_discord_source_runtime_rejects_import_after_close(tmp_path: Path) -> None:
    class FakeClient:
        async def close(self) -> None:
            pass

    runtime = DiscordSourceRuntime(FakeClient(), guild_ids=(1,))
    runtime.close()

    with pytest.raises(AdapterError, match="closed"):
        runtime.import_to_archive(ArchivePaths(tmp_path / "archive"))


def test_build_discord_source_runtime_config_uses_override_token() -> None:
    from archive_sync_engine.adapters.discord.runtime import build_discord_source_runtime_config

    config = build_discord_source_runtime_config(
        SimpleNamespace(discord_token="configured-token"),
        ("123",),
        {"token": "override-token"},
    )

    assert config.token == "override-token"
    assert config.guild_ids == (123,)
