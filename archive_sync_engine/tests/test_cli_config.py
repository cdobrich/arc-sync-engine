from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from archive_sync_engine.cli import main
from archive_sync_engine.archive.package import ArchivePackage
from archive_sync_engine.archive.paths import ArchivePaths


def test_sync_cli_loads_yaml_setup_configuration(tmp_path: Path) -> None:
    (tmp_path / "discord.token").write_text("discord-secret\n", encoding="utf-8")
    (tmp_path / "fluxer.token").write_text("fluxer-secret\n", encoding="utf-8")
    (tmp_path / "bob.key").write_text("bob-secret\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token_file: discord.token
  guild_id: 123
fluxer:
  token_file: fluxer.token
  server_id: fluxer-server
user_mappings:
  discord:
    "987654321":
      fluxer_username: BobOnFluxer#0909
      fluxer_auth_key_file: bob.key
""",
        encoding="utf-8",
    )

    ArchivePackage.initialize(ArchivePaths(tmp_path / "archive"))

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None

    with patch(
        "archive_sync_engine.sync.discord_fluxer_runtime.DiscordFluxerSyncRuntime.from_runtime_request",
        return_value=runtime,
    ) as runtime_type:
        assert main(["sync", "--config", str(config)]) == 0

    runtime_config = runtime_type.call_args.args[0]
    assert runtime_config.adapter_config["discord"].token == "discord-secret"
    assert runtime_config.adapter_config["discord"].guild_ids == (123,)
    assert runtime_config.adapter_config["fluxer"].token == "fluxer-secret"
    assert runtime_config.destination_scope == ("fluxer-server",)
    assert runtime_config.archive_path == (tmp_path / "archive").resolve()
    assert runtime_config.adapter_config["identity_mappings"][0].username == "discord:user:987654321"
    assert runtime_config.adapter_config["identity_mappings"][0].fluxer_auth_key == "bob-secret"


def test_sync_cli_arguments_override_yaml_configuration(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./configured-archive
discord:
  token: configured-discord
guild_id: wrong
discord:
  token: configured-discord
  guild_id: 111
fluxer:
  token: configured-fluxer
  server_id: configured-server
""",
        encoding="utf-8",
    )

    ArchivePackage.initialize(ArchivePaths(tmp_path / "cli-archive"))

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None

    with patch(
        "archive_sync_engine.sync.discord_fluxer_runtime.DiscordFluxerSyncRuntime.from_runtime_request",
        return_value=runtime,
    ) as runtime_type:
        assert (
            main(
                [
                    "sync",
                    "--config",
                    str(config),
                    "--discord-token",
                    "cli-discord",
                    "--discord-guild-id",
                    "222",
                    "--fluxer-token",
                    "cli-fluxer",
                    "--fluxer-guild-id",
                    "cli-server",
                    "--archive",
                    str(tmp_path / "cli-archive"),
                ]
            )
            == 0
        )

    runtime_config = runtime_type.call_args.args[0]
    assert runtime_config.adapter_config["discord"].token == "cli-discord"
    assert runtime_config.adapter_config["discord"].guild_ids == (222,)
    assert runtime_config.adapter_config["fluxer"].token == "cli-fluxer"
    assert runtime_config.destination_scope == ("cli-server",)
    assert runtime_config.archive_path == (tmp_path / "cli-archive").resolve()
