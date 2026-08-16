from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from archive_sync_engine.cli import build_parser, main
from archive_sync_engine.sync.run_configuration import RunDirection, SyncRunConfiguration
from archive_sync_engine.archive.package import ArchivePackage
from archive_sync_engine.archive.paths import ArchivePaths


def test_sync_cli_builds_runtime_configuration() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "sync",
            "--discord-token",
            "discord-token",
            "--discord-guild-id",
            "10",
            "--discord-guild-id",
            "20",
            "--fluxer-token",
            "fluxer-token",
            "--fluxer-guild-id",
            "guild-1",
            "--archive",
            "/tmp/archive",
            "--fluxer-identity",
            "alice:alice-token",
            "--fluxer-identity",
            "bob",
            "--resume",
        ]
    )

    assert args.command == "sync"
    assert args.discord_guild_id == [10, 20]
    assert args.archive == Path("/tmp/archive")
    assert args.resume is True
    assert args.fluxer_identity == ["alice:alice-token", "bob"]


def test_sync_cli_constructs_runtime_and_runs_resume(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None

    with patch(
        "archive_sync_engine.cli.DiscordFluxerSyncRuntime",
        return_value=runtime,
    ) as runtime_type:
        result = main(
            [
                "sync",
                "--discord-token",
                "discord-token",
                "--discord-guild-id",
                "10",
                "--fluxer-token",
                "fluxer-token",
                "--fluxer-guild-id",
                "guild-1",
                "--archive",
                str(archive_path),
                "--resume",
            ]
        )

    assert result == 0
    runtime_type.assert_called_once()
    runtime.run.assert_called_once_with(resume_import=True)

    from archive_sync_engine.sync.run_configuration import RunDirection

    persisted = ArchivePackage(ArchivePaths(archive_path)).load_run_configuration()
    assert persisted.direction is RunDirection.SYNC
    assert persisted.input_adapter == "discord"
    assert persisted.input_scope == ("10",)
    assert persisted.destination_adapter == "fluxer"
    assert persisted.destination_scope == ("guild-1",)
    runtime.__exit__.assert_called_once()


def test_sync_cli_maps_bot_identity_without_auth_token(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None

    with patch(
        "archive_sync_engine.cli.DiscordFluxerSyncRuntime",
        return_value=runtime,
    ) as runtime_type:
        assert (
            main(
                [
                    "sync",
                    "--discord-token",
                    "discord-token",
                    "--discord-guild-id",
                    "10",
                    "--fluxer-token",
                    "fluxer-token",
                    "--fluxer-guild-id",
                    "guild-1",
                    "--archive",
                    str(archive_path),
                    "--fluxer-identity",
                    "bot-user",
                ]
            )
            == 0
        )

    config = runtime_type.call_args.args[0]
    assert config.identity_mappings[0].username == "bot-user"
    assert config.identity_mappings[0].fluxer_auth_key is None


def test_adapters_cli_lists_supported_sync_pairs(capsys) -> None:
    assert main(["adapters"]) == 0

    output = capsys.readouterr().out
    assert "SUPPORTED SYNC PAIRS" in output
    assert "discord\tfluxer" in output


def test_adapters_cli_json_includes_supported_sync_pairs(capsys) -> None:
    import json

    assert main(["adapters", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["sync_pairs"] == [
        {
            "description": "Discord import synchronized to Fluxer.",
            "destination_adapter": "fluxer",
            "input_adapter": "discord",
        }
    ]


def test_diagnostics_cli_queries_execution_log_and_prints_table(tmp_path: Path, capsys) -> None:
    from archive_sync_engine.adapters.references import DestinationMessageRef
    from archive_sync_engine.executor import ExecutionResult
    from archive_sync_engine.operations import EditMessageOperation
    from archive_sync_engine.repository import SQLiteStateRepository
    from archive_sync_engine.sync import SynchronizationState

    state_path = tmp_path / "synchronization.sqlite"
    with SQLiteStateRepository(state_path) as repository:
        repository.record_execution(
            operation=EditMessageOperation(message=Mock()),
            result=ExecutionResult(canonical_id="message-001"),
            synchronization_state=SynchronizationState(
                messages={"message-001": DestinationMessageRef("destination-001")},
            ),
        )

    assert main(["diagnostics", "--archive", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "OPERATION" in output
    assert "message-001" in output


def test_diagnostics_cli_json_output_supports_filters(tmp_path: Path, capsys) -> None:
    from archive_sync_engine.adapters.references import DestinationMessageRef
    from archive_sync_engine.executor import ExecutionResult
    from archive_sync_engine.operations import EditMessageOperation
    from archive_sync_engine.repository import SQLiteStateRepository
    from archive_sync_engine.sync import SynchronizationState

    state_path = tmp_path / "synchronization.sqlite"
    with SQLiteStateRepository(state_path) as repository:
        repository.record_execution(
            operation=EditMessageOperation(message=Mock()),
            result=ExecutionResult(canonical_id="message-001"),
            synchronization_state=SynchronizationState(
                messages={"message-001": DestinationMessageRef("destination-001")},
            ),
        )
        repository.record_execution(
            operation=EditMessageOperation(message=Mock()),
            result=ExecutionResult(canonical_id="message-002"),
            synchronization_state=SynchronizationState(
                messages={"message-002": DestinationMessageRef("destination-002")},
            ),
        )

    assert (
        main(
            [
                "diagnostics",
                "--archive",
                str(tmp_path),
                "--canonical-id",
                "message-001",
                "--json",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert '"canonical_id": "message-001"' in output
    assert "message-002" not in output


def test_diagnostics_cli_negative_limit_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "diagnostics",
                "--archive",
                str(tmp_path),
                "--limit",
                "-1",
            ]
        )


def test_sync_cli_cli_credentials_override_environment(monkeypatch, tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))
    monkeypatch.setenv("ARCHIVE_SYNC_DISCORD_TOKEN", "discord-env")
    monkeypatch.setenv("ARCHIVE_SYNC_FLUXER_TOKEN", "fluxer-env")

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None

    with patch("archive_sync_engine.cli.DiscordFluxerSyncRuntime", return_value=runtime) as runtime_type:
        assert (
            main(
                [
                    "sync",
                    "--discord-token", "discord-cli",
                    "--discord-guild-id", "10",
                    "--fluxer-token", "fluxer-cli",
                    "--fluxer-guild-id", "guild-cli",
                    "--archive", str(archive_path),
                ]
            )
            == 0
        )

    config = runtime_type.call_args.args[0]
    assert config.discord.token == "discord-cli"
    assert config.fluxer.token == "fluxer-cli"
    assert config.fluxer_guild_id == "guild-cli"
    assert config.archive_paths.root == archive_path


def test_sync_cli_rejects_missing_credentials(monkeypatch) -> None:
    monkeypatch.delenv("ARCHIVE_SYNC_DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("ARCHIVE_SYNC_FLUXER_TOKEN", raising=False)

    with pytest.raises(SystemExit):
        main(
            [
                "sync",
                "--discord-guild-id", "10",
                "--fluxer-guild-id", "guild",
                "--archive", "/tmp/archive",
            ]
        )


def test_sync_cli_rejects_invalid_config(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "invalid.toml"
    config_path.write_text("[sync\n", encoding="utf-8")
    monkeypatch.setenv("ARCHIVE_SYNC_DISCORD_TOKEN", "discord")
    monkeypatch.setenv("ARCHIVE_SYNC_FLUXER_TOKEN", "fluxer")

    with pytest.raises(SystemExit):
        main(["--config", str(config_path), "sync"])


def test_resume_cli_reuses_persisted_scopes_but_requires_current_credentials(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))
    ArchivePackage(ArchivePaths(archive_path)).save_run_configuration(
        SyncRunConfiguration(
            direction=RunDirection.SYNC,
            input_adapter="discord",
            input_scope=("10", "20"),
            destination_adapter="fluxer",
            destination_scope=("fluxer-guild",),
        )
    )
    from archive_sync_engine.sync.session import SyncDirection, SyncSession
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    ArchivePackage(ArchivePaths(archive_path)).save_session(
        SyncSession(id="sync-1", direction=SyncDirection.EXPORT, started_at=now, updated_at=now)
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord-secret
  guild_id: 999
fluxer:
  token: fluxer-secret
  server_id: config-guild
""",
        encoding="utf-8",
    )

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    with patch("archive_sync_engine.cli.DiscordFluxerSyncRuntime", return_value=runtime) as runtime_type:
        assert main(["resume", "--config", str(config)]) == 0

    runtime_type.assert_called_once()
    config_arg = runtime_type.call_args.args[0]
    assert config_arg.discord.guild_ids == (10, 20)
    assert config_arg.fluxer_guild_id == "fluxer-guild"
    runtime.run.assert_called_once_with(resume_import=True)


def test_resume_cli_rejects_completed_persisted_run(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))
    ArchivePackage(ArchivePaths(archive_path)).save_run_configuration(
        SyncRunConfiguration(
            direction=RunDirection.SYNC,
            input_adapter="discord",
            input_scope=("10",),
            destination_adapter="fluxer",
            destination_scope=("fluxer-guild",),
        )
    )
    from archive_sync_engine.sync.session import SyncDirection, SyncSession
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    ArchivePackage(ArchivePaths(archive_path)).save_session(
        SyncSession(id="sync-1", direction=SyncDirection.EXPORT, started_at=now, updated_at=now, completed=True)
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord-secret
  guild_id: 10
fluxer:
  token: fluxer-secret
  server_id: fluxer-guild
""",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        main(["resume", "--config", str(config)])


def test_sync_cli_dry_run_does_not_persist_run_configuration(tmp_path: Path, capsys) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    runtime.dry_run.return_value = (Mock(), Mock())

    with patch(
        "archive_sync_engine.cli.DiscordFluxerSyncRuntime",
        return_value=runtime,
    ):
        assert (
            main(
                [
                    "sync",
                    "--discord-token", "discord-token",
                    "--discord-guild-id", "10",
                    "--fluxer-token", "fluxer-token",
                    "--fluxer-guild-id", "guild-1",
                    "--archive", str(archive_path),
                    "--dry-run",
                ]
            )
            == 0
        )

    runtime.dry_run.assert_called_once_with()
    runtime.run.assert_not_called()
    assert not (archive_path / "run.json").exists()
    assert "2 synchronization operations planned" in capsys.readouterr().out


def test_sync_cli_rejects_dry_run_with_resume() -> None:
    with pytest.raises(SystemExit):
        main(["sync", "--dry-run", "--resume", "--discord-token", "discord", "--discord-guild-id", "10", "--fluxer-token", "fluxer", "--fluxer-guild-id", "guild", "--archive", "/tmp/archive"])


def test_diagnostics_summary_cli_reports_archive_and_operational_state(
    tmp_path: Path,
    capsys,
) -> None:
    from archive_sync_engine.archive.package import ArchivePackage
    from archive_sync_engine.archive.paths import ArchivePaths

    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))

    assert main(["diagnostics", "--archive", str(archive_path), "--summary"]) == 0
    output = capsys.readouterr().out
    assert "Integrity: VALID" in output
    assert "Canonical records:" in output
    assert "Run configuration: none" in output
    assert "Session: none" in output
    assert "Synchronization state: present=false" in output


def test_diagnostics_summary_json_is_read_only_and_reports_invalid_archive(
    tmp_path: Path,
    capsys,
) -> None:
    archive_path = tmp_path / "missing"

    assert main(
        ["diagnostics", "--archive", str(archive_path), "--summary", "--json"]
    ) == 1
    output = capsys.readouterr().out
    assert '"valid": false' in output
    assert "does not exist" in output
    assert not archive_path.exists()


def test_preflight_validates_configuration_and_archive_without_writing(tmp_path: Path, capsys) -> None:
    (tmp_path / "discord.token").write_text("discord-secret\n", encoding="utf-8")
    (tmp_path / "fluxer.token").write_text("fluxer-secret\n", encoding="utf-8")
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
user_mappings: {}
""",
        encoding="utf-8",
    )
    ArchivePackage.initialize(ArchivePaths(tmp_path / "archive"))
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))

    assert main(["preflight", "--config", str(config)]) == 0

    output = capsys.readouterr().out
    assert "Ready: YES" in output
    assert "discord-secret" not in output
    assert "fluxer-secret" not in output
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert after == before


def test_preflight_json_reports_missing_archive_without_exposing_secrets(tmp_path: Path, capsys) -> None:
    (tmp_path / "discord.token").write_text("discord-secret\n", encoding="utf-8")
    (tmp_path / "fluxer.token").write_text("fluxer-secret\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./missing
discord:
  token_file: discord.token
  guild_id: 123
fluxer:
  token_file: fluxer.token
  server_id: fluxer-server
""",
        encoding="utf-8",
    )

    assert main(["preflight", "--config", str(config), "--json"]) == 1

    import json
    rendered = capsys.readouterr().out
    payload = json.loads(rendered)
    assert payload["ready"] is False
    assert payload["configuration"]["credentials_resolved"] is True
    assert payload["archive"]["initialized"] is False
    assert "discord-secret" not in rendered
    assert "fluxer-secret" not in rendered


def test_adapters_cli_lists_registered_roles(capsys) -> None:
    assert main(["adapters"]) == 0
    output = capsys.readouterr().out
    assert "NAME\tSOURCE\tDESTINATION" in output
    assert "discord\ttrue\tfalse" in output
    assert "fluxer\tfalse\ttrue" in output


def test_adapters_cli_json_is_machine_readable(capsys) -> None:
    import json

    assert main(["adapters", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {entry["name"] for entry in payload["adapters"]} == {"discord", "fluxer"}
    assert payload["sync_pairs"][0]["input_adapter"] == "discord"
    assert payload["sync_pairs"][0]["destination_adapter"] == "fluxer"
    assert next(entry for entry in payload["adapters"] if entry["name"] == "discord")["source"] is True


def test_sync_rejects_unregistered_adapter_pair(monkeypatch) -> None:
    from archive_sync_engine.adapters import SyncPairRegistry
    from archive_sync_engine.cli import _require_supported_sync_pair
    from archive_sync_engine.config import ConfigurationError

    monkeypatch.setattr(
        "archive_sync_engine.cli.default_sync_pair_registry",
        lambda: SyncPairRegistry(),
    )

    with pytest.raises(ConfigurationError, match="Unsupported sync adapter pair"):
        _require_supported_sync_pair("fluxer", "fluxer")


def test_import_cli_uses_source_runtime_registry_and_persists_generic_run_configuration(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord-secret
  guild_id: 123
fluxer:
  token: fluxer-secret
  server_id: fluxer-server
""",
        encoding="utf-8",
    )

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None

    registry = MagicMock()
    registry.create.return_value = runtime

    with patch(
        "archive_sync_engine.cli.default_source_runtime_registry",
        return_value=registry,
    ) as registry_factory:
        assert main(["import", "--config", str(config)]) == 0

    registry_factory.assert_called_once()
    registry.create.assert_called_once()
    request = registry.create.call_args.args[1]
    assert request.adapter == "discord"
    assert request.scope == ("123",)
    assert request.archive_path == archive_path.resolve()
    assert request.adapter_config["discord"].token == "discord-secret"
    runtime.import_to_archive.assert_called_once_with(
        ArchivePaths(archive_path.resolve()),
        resume=False,
    )

    persisted = ArchivePackage(ArchivePaths(archive_path)).load_run_configuration()
    assert persisted.direction is RunDirection.IMPORT
    assert persisted.input_adapter == "discord"
    assert persisted.input_scope == ("123",)
    assert persisted.destination_adapter is None
    assert persisted.destination_scope == ()


def test_import_cli_resume_uses_persisted_scope_and_current_credentials(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))
    package = ArchivePackage(ArchivePaths(archive_path))
    package.save_run_configuration(
        SyncRunConfiguration(
            direction=RunDirection.IMPORT,
            input_adapter="discord",
            input_scope=("10", "20"),
        )
    )
    from archive_sync_engine.importer import ImportState

    package.save_import_state(ImportState(payload={"guild": "20"}))
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    package.save_session(
        __import__("archive_sync_engine.sync.session", fromlist=["SyncSession"]).SyncSession(
            id="import-session",
            direction=__import__("archive_sync_engine.sync.session", fromlist=["SyncDirection"]).SyncDirection.IMPORT,
            started_at=now,
            updated_at=now,
        )
    )

    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: current-discord-secret
  guild_id: 999
fluxer:
  token: fluxer-secret
  server_id: fluxer-server
""",
        encoding="utf-8",
    )

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    registry = MagicMock()
    registry.create.return_value = runtime

    with patch(
        "archive_sync_engine.cli.default_source_runtime_registry",
        return_value=registry,
    ):
        assert main(["resume", "--config", str(config)]) == 0

    request = registry.create.call_args.args[1]
    assert request.adapter == "discord"
    assert request.scope == ("10", "20")
    assert request.adapter_config["discord"].token == "current-discord-secret"
    runtime.import_to_archive.assert_called_once_with(
        ArchivePaths(archive_path.resolve()),
        resume=True,
    )


def test_import_cli_resume_rejects_scope_changes_against_persisted_run(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))
    package = ArchivePackage(ArchivePaths(archive_path))
    package.save_run_configuration(
        SyncRunConfiguration(
            direction=RunDirection.IMPORT,
            input_adapter="discord",
            input_scope=("10",),
        )
    )
    from archive_sync_engine.importer import ImportState

    package.save_import_state(ImportState(payload={"guild": "10"}))
    from datetime import datetime, timezone
    from archive_sync_engine.sync.session import SyncDirection, SyncSession

    now = datetime.now(timezone.utc)
    package.save_session(
        SyncSession(
            id="import-session",
            direction=SyncDirection.IMPORT,
            started_at=now,
            updated_at=now,
        )
    )

    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: current-discord-secret
  guild_id: 999
fluxer:
  token: fluxer-secret
  server_id: fluxer-server
""",
        encoding="utf-8",
    )

    with patch("archive_sync_engine.cli.default_source_runtime_registry") as registry:
        registry.create.return_value = MagicMock()
        with pytest.raises(SystemExit):
            main(
                [
                    "import",
                    "--config",
                    str(config),
                    "--resume",
                    "--input-scope",
                    "999",
                ]
            )
        registry.create.assert_not_called()


def test_export_cli_uses_destination_runtime_registry_and_canonical_exporter(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord-secret
  guild_id: 123
fluxer:
  token: fluxer-secret
  server_id: fluxer-server
""",
        encoding="utf-8",
    )

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    runtime.adapter = object()

    registry = MagicMock()
    registry.create.return_value = runtime

    exporter = MagicMock()

    with (
        patch(
            "archive_sync_engine.cli.default_destination_runtime_registry",
            return_value=registry,
        ) as registry_factory,
        patch(
            "archive_sync_engine.cli.CanonicalExporter",
            return_value=exporter,
        ) as exporter_type,
    ):
        assert main(["export", "--config", str(config)]) == 0

    registry_factory.assert_called_once()
    registry.create.assert_called_once()
    request = registry.create.call_args.args[1]
    assert request.adapter == "fluxer"
    assert request.scope == ("fluxer-server",)
    assert request.archive_path == archive_path.resolve()
    assert request.adapter_config["fluxer"].token == "fluxer-secret"

    exporter_type.assert_called_once()
    exporter.export.assert_called_once()
    assert exporter.export.call_args.kwargs["destination"] is runtime.adapter
    assert exporter.export.call_args.kwargs["archive"].package.paths.root == archive_path.resolve()


def test_export_cli_allows_destination_scope_override(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord-secret
  guild_id: 123
fluxer:
  token: fluxer-secret
  server_id: configured-server
""",
        encoding="utf-8",
    )

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    runtime.adapter = object()
    registry = MagicMock()
    registry.create.return_value = runtime

    with (
        patch(
            "archive_sync_engine.cli.default_destination_runtime_registry",
            return_value=registry,
        ),
        patch("archive_sync_engine.cli.CanonicalExporter"),
    ):
        assert main(
            [
                "export",
                "--config",
                str(config),
                "--destination-scope",
                "override-server",
            ]
        ) == 0

    request = registry.create.call_args.args[1]
    assert request.scope == ("override-server",)


def test_export_cli_rejects_uninitialized_archive(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord-secret
  guild_id: 123
fluxer:
  token: fluxer-secret
  server_id: configured-server
""",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        main(["export", "--config", str(config)])


def test_export_cli_uses_destination_registry_for_unknown_adapter(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord-secret
  guild_id: 123
fluxer:
  token: fluxer-secret
  server_id: configured-server
""",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        main(
            [
                "export",
                "--config",
                str(config),
                "--destination-adapter",
                "future-platform",
            ]
        )
