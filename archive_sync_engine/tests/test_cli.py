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
