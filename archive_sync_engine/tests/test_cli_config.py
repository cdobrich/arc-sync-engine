from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from archive_sync_engine.cli import main
from archive_sync_engine.config import load_setup_configuration
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

    sync_registry = MagicMock()
    sync_registry.create.return_value = runtime
    with patch(
        "archive_sync_engine.cli.default_sync_runtime_registry",
        return_value=sync_registry,
    ):
        assert main(["sync", "--config", str(config)]) == 0

    request = sync_registry.create.call_args.args[2]
    assert request.input_adapter == "discord"
    assert request.input_scope == ("123",)
    assert request.destination_adapter == "fluxer"
    assert request.destination_scope == ("fluxer-server",)
    assert request.archive_path == (tmp_path / "archive").resolve()
    assert request.adapter_config["discord"].token == "discord-secret"
    assert request.adapter_config["discord"].guild_ids == (123,)
    assert request.adapter_config["fluxer"].token == "fluxer-secret"
    assert request.adapter_config["identity_mappings"][0].username == "discord:user:987654321"
    assert request.adapter_config["identity_mappings"][0].fluxer_auth_key == "bob-secret"


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

    sync_registry = MagicMock()
    sync_registry.create.return_value = runtime
    with patch(
        "archive_sync_engine.cli.default_sync_runtime_registry",
        return_value=sync_registry,
    ):
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

    request = sync_registry.create.call_args.args[2]
    assert request.input_adapter == "discord"
    assert request.input_scope == ("222",)
    assert request.destination_adapter == "fluxer"
    assert request.destination_scope == ("cli-server",)
    assert request.archive_path == (tmp_path / "cli-archive").resolve()
    assert request.adapter_config["discord"].token == "cli-discord"
    assert request.adapter_config["discord"].guild_ids == (222,)
    assert request.adapter_config["fluxer"].token == "cli-fluxer"


def test_import_cli_requires_only_source_adapter_configuration(tmp_path: Path) -> None:
    (tmp_path / "discord.token").write_text("discord-secret\n", encoding="utf-8")
    config = tmp_path / "source-only.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token_file: discord.token
  guild_id: 123
""",
        encoding="utf-8",
    )
    ArchivePackage.initialize(ArchivePaths(tmp_path / "archive"))

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    registry = MagicMock()
    registry.create.return_value = runtime
    registry.build_config.return_value = type("DiscordConfig", (), {"token": "discord-secret"})()
    with patch(
        "archive_sync_engine.cli.default_source_runtime_registry",
        return_value=registry,
    ) as registry_factory:
        assert main(["import", "--config", str(config)]) == 0

    request = registry.create.call_args.args[1]
    assert request.adapter == "discord"
    assert request.scope == ("123",)
    assert request.adapter_config["discord"].token == "discord-secret"


def test_export_cli_requires_only_destination_adapter_configuration(tmp_path: Path) -> None:
    (tmp_path / "fluxer.token").write_text("fluxer-secret\n", encoding="utf-8")
    config = tmp_path / "destination-only.yaml"
    config.write_text(
        """
archive:
  path: ./archive
fluxer:
  token_file: fluxer.token
  server_id: fluxer-server
""",
        encoding="utf-8",
    )
    ArchivePackage.initialize(ArchivePaths(tmp_path / "archive"))

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    registry = MagicMock()
    registry.create.return_value = runtime
    registry.build_config.return_value = {"fluxer": type("FluxerConfig", (), {"token": "fluxer-secret"})()}
    with patch(
        "archive_sync_engine.cli.default_destination_runtime_registry",
        return_value=registry,
    ) as registry_factory:
        with patch("archive_sync_engine.cli.CanonicalExporter") as exporter_type:
            exporter_type.return_value.export.return_value = type(
                "Report", (), {"executed_operations": 0}
            )()
            assert main(["export", "--config", str(config)]) == 0

    request = registry.create.call_args.args[1]
    assert request.adapter == "fluxer"
    assert request.scope == ("fluxer-server",)
    assert request.adapter_config["fluxer"].token == "fluxer-secret"


def test_directional_credentials_do_not_resolve_unused_adapter_secrets(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord-secret
  guild_id: 123
fluxer:
  token_file: missing-fluxer-secret.key
  server_id: fluxer-server
""",
        encoding="utf-8",
    )

    setup = load_setup_configuration(config)
    credentials = setup.resolve_credentials(require_discord=True, require_fluxer=False)

    assert credentials.discord_token == "discord-secret"
    assert credentials.fluxer_token == ""
