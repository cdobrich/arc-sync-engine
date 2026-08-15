from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from archive_sync_engine.cli import build_parser, main


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


def test_sync_cli_constructs_runtime_and_runs_resume() -> None:
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
                "/tmp/archive",
                "--resume",
            ]
        )

    assert result == 0
    runtime_type.assert_called_once()
    runtime.run.assert_called_once_with(resume_import=True)
    runtime.__exit__.assert_called_once()


def test_sync_cli_maps_bot_identity_without_auth_token() -> None:
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
                    "/tmp/archive",
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


def test_sync_cli_cli_credentials_override_environment(monkeypatch) -> None:
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
                    "--archive", "/cli/archive",
                ]
            )
            == 0
        )

    config = runtime_type.call_args.args[0]
    assert config.discord.token == "discord-cli"
    assert config.fluxer.token == "fluxer-cli"
    assert config.fluxer_guild_id == "guild-cli"
    assert config.archive_paths.root == Path("/cli/archive")


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


def test_init_cli_creates_archive_package(tmp_path: Path, capsys) -> None:
    archive_path = tmp_path / "archive"

    assert main(["init", "--archive", str(archive_path)]) == 0

    output = capsys.readouterr().out
    assert "Initialized Archive Package" in output
    assert (archive_path / "archive.sqlite").is_file()
    assert (archive_path / "manifest.json").is_file()
    assert (archive_path / "attachments").is_dir()


def test_init_cli_rejects_existing_nonempty_archive(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    archive_path.mkdir()
    (archive_path / "existing.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(SystemExit):
        main(["init", "--archive", str(archive_path)])

    assert (archive_path / "existing.txt").read_text(encoding="utf-8") == "keep"


def test_init_cli_requires_archive_path() -> None:
    with pytest.raises(SystemExit):
        main(["init"])
