from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from archive_sync_engine.cli import build_parser, main
from archive_sync_engine.sync.run_configuration import RunDirection, SyncRunConfiguration
from archive_sync_engine.archive.package import ArchivePackage
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive import validate_archive_package
from archive_sync_engine.repository.sqlite_state_repository import SQLiteStateRepository



def test_print_export_progress_renders_adapter_neutral_phases(capsys) -> None:
    from archive_sync_engine.cli import _print_export_progress
    from archive_sync_engine.sync.progress import SyncProgress

    _print_export_progress(SyncProgress(phase="identities", current=1, detail="identity-1"))
    _print_export_progress(SyncProgress(phase="conversations", current=2, detail="conversation-2"))
    _print_export_progress(SyncProgress(phase="messages", current=3, detail="message-3"))
    _print_export_progress(SyncProgress(phase="attachments", current=1, detail="photo.png"))

    output = capsys.readouterr().out
    assert "Exporting identities 1: identity-1..." in output
    assert "Exporting conversations 2: conversation-2..." in output
    assert "Exporting messages 3 [message-3]..." in output
    assert "Exporting attachment 1 [photo.png]..." in output


def test_print_import_progress_renders_adapter_neutral_phases(capsys) -> None:
    from archive_sync_engine.cli import _print_import_progress
    from archive_sync_engine.importer.progress import ImportProgress

    _print_import_progress(ImportProgress(phase="identities", current=1, detail="user-1"))
    _print_import_progress(
        ImportProgress(
            phase="conversations",
            current=2,
            total=4,
            completed=1,
            detail="General",
        )
    )
    _print_import_progress(
        ImportProgress(
            phase="conversations",
            current=2,
            total=4,
            completed=2,
            detail="General",
        )
    )
    _print_import_progress(ImportProgress(phase="messages", current=3, total=10, detail="message-3"))
    _print_import_progress(ImportProgress(phase="attachments", current=1, total=2, detail="photo.png"))
    _print_import_progress(
        ImportProgress(
            phase="refresh",
            mode="incremental",
            traversal="adapter_incremental",
            cursor="message-42",
            lookback_seconds=604800,
            detail="conversation-1",
        )
    )
    _print_import_progress(
        ImportProgress(
            phase="refresh",
            mode="incremental",
            traversal="completed",
            examined=3,
            attachments_downloaded=1,
            attachments_reused=2,
            detail="source refresh complete",
        )
    )

    output = capsys.readouterr().out
    assert "Importing identity 1 (user-1)..." in output
    assert "Importing conversation 2 of 4 (1 completed, 3 remaining): General..." in output
    assert "Imported conversation 2 of 4 (2 completed, 2 remaining): General." in output
    assert "Importing messages 3 of 10 [message-3]..." in output
    assert "Importing attachment 1 of 2: photo.png..." in output
    assert "Import refresh: mode=incremental; traversal=adapter_incremental; cursor=message-42; lookback=604800s; conversation-1." in output
    assert "Import refresh completed: mode=incremental; examined=3; attachments_downloaded=1; attachments_reused=2." in output


def test_print_import_progress_uses_tqdm_for_identity_discovery(monkeypatch) -> None:
    from archive_sync_engine import cli
    from archive_sync_engine.cli import _print_import_progress
    from archive_sync_engine.importer.progress import ImportProgress

    class FakeTqdm:
        instances = []

        def __init__(self, *, total, desc, unit, dynamic_ncols, file):
            self.total = total
            self.desc = desc
            self.unit = unit
            self.dynamic_ncols = dynamic_ncols
            self.file = file
            self.n = 0
            self.updates = []
            self.postfixes = []
            self.closed = False
            self.__class__.instances.append(self)

        def update(self, amount):
            self.n += amount
            self.updates.append(amount)

        def set_postfix_str(self, value, *, refresh):
            self.postfixes.append((value, refresh))

        def close(self):
            self.closed = True

    monkeypatch.setattr(cli, "tqdm", FakeTqdm)
    monkeypatch.setattr(cli, "_import_progress_is_tty", lambda: True)
    cli._IMPORT_PROGRESS_BAR = None
    cli._IMPORT_DISCOVERY_BAR = None

    _print_import_progress(
        ImportProgress(
            phase="identity_scan",
            current=0,
            detail="Loading Discord guild members...",
        )
    )
    _print_import_progress(
        ImportProgress(
            phase="identity_scan",
            current=300,
            detail="Scanning Discord history in #general",
        )
    )

    scan_bar = FakeTqdm.instances[0]
    assert scan_bar.total is None
    assert scan_bar.desc == "Discovering identities"
    assert scan_bar.unit == "message"
    assert scan_bar.updates == [300]
    assert scan_bar.postfixes[-1] == ("Scanning Discord history in #general", True)

    _print_import_progress(ImportProgress(phase="identities", current=0))
    _print_import_progress(
        ImportProgress(
            phase="identities",
            current=300,
            detail="discord:user:123",
        )
    )

    assert scan_bar.closed is True
    identity_bar = FakeTqdm.instances[1]
    assert identity_bar.total is None
    assert identity_bar.desc == "Importing identities"
    assert identity_bar.unit == "identity"
    assert identity_bar.updates == [300]
    assert identity_bar.postfixes == [("current=discord:user:123", True)]

    _print_import_progress(ImportProgress(phase="conversations", current=0, total=1, completed=0))
    assert identity_bar.closed is True
    cli._IMPORT_PROGRESS_BAR = None
    cli._IMPORT_DISCOVERY_BAR = None


def test_print_import_progress_reports_identity_resume_checkpoint(capsys) -> None:
    from archive_sync_engine.cli import _print_import_progress
    from archive_sync_engine.importer import ImportProgress

    _print_import_progress(
        ImportProgress(
            phase="identity_scan",
            current=0,
            detail=(
                "Resuming identity discovery from checkpoint: "
                "400 identities committed; cursor={'stage': 'history', 'message_index': 91}"
            ),
        )
    )

    output = capsys.readouterr().out
    assert "Resuming identity discovery from checkpoint" in output
    assert "400 identities committed" in output


def test_print_import_progress_reports_identity_discovery(capsys) -> None:
    from archive_sync_engine.cli import _print_import_progress
    from archive_sync_engine.importer import ImportProgress

    _print_import_progress(
        ImportProgress(
            phase="identity_scan",
            current=0,
            detail="Scanning #general (discord:guild:1:channel:2) history...",
        )
    )
    _print_import_progress(
        ImportProgress(
            phase="identity_scan",
            current=100,
            detail="Scanning Discord history in #general",
        )
    )

    output = capsys.readouterr().out
    assert "Identity discovery: Scanning #general" in output
    assert "scanned 100 historical messages" in output


def test_print_import_progress_uses_tqdm_for_conversation_progress(monkeypatch) -> None:
    from archive_sync_engine import cli
    from archive_sync_engine.cli import _print_import_progress
    from archive_sync_engine.importer.progress import ImportProgress

    class FakeTqdm:
        instances = []

        def __init__(self, *, total, desc, unit, dynamic_ncols, file):
            self.total = total
            self.desc = desc
            self.unit = unit
            self.dynamic_ncols = dynamic_ncols
            self.file = file
            self.n = 0
            self.updates = []
            self.postfixes = []
            self.closed = False
            self.__class__.instances.append(self)

        def update(self, amount):
            self.n += amount
            self.updates.append(amount)

        def set_postfix_str(self, value, *, refresh):
            self.postfixes.append((value, refresh))

        def close(self):
            self.closed = True

    monkeypatch.setattr(cli, "tqdm", FakeTqdm)
    monkeypatch.setattr(cli, "_import_progress_is_tty", lambda: True)
    cli._IMPORT_PROGRESS_BAR = None

    _print_import_progress(
        ImportProgress(
            phase="conversations",
            current=1,
            total=3,
            completed=0,
            detail="General",
        )
    )
    _print_import_progress(
        ImportProgress(
            phase="messages",
            current=7,
            total=10,
            detail="message-7",
        )
    )
    _print_import_progress(
        ImportProgress(
            phase="conversations",
            current=1,
            total=3,
            completed=1,
            detail="General",
        )
    )

    bar = FakeTqdm.instances[0]
    assert bar.total == 3
    assert bar.desc == "Importing conversations"
    assert bar.unit == "conversation"
    assert bar.dynamic_ncols is True
    assert bar.updates == [1]
    assert bar.postfixes == [
        ("current=General", True),
        ("messages=7/10 current=message-7", True),
        ("current=General", True),
    ]
    assert bar.closed is False
    assert cli._IMPORT_PROGRESS_BAR is bar

    _print_import_progress(
        ImportProgress(
            phase="conversations",
            current=3,
            total=3,
            completed=3,
            detail="Last",
        )
    )
    assert bar.updates == [1, 2]
    assert bar.closed is True
    assert cli._IMPORT_PROGRESS_BAR is None


def test_print_import_progress_closes_tqdm_before_non_conversation_output(monkeypatch, capsys) -> None:
    from archive_sync_engine import cli
    from archive_sync_engine.cli import _print_import_progress
    from archive_sync_engine.importer.progress import ImportProgress

    class FakeTqdm:
        def __init__(self, **kwargs):
            self.total = kwargs["total"]
            self.n = 0
            self.closed = False

        def update(self, amount):
            self.n += amount

        def set_postfix_str(self, value, *, refresh):
            pass

        def close(self):
            self.closed = True

    monkeypatch.setattr(cli, "tqdm", FakeTqdm)
    monkeypatch.setattr(cli, "_import_progress_is_tty", lambda: True)
    cli._IMPORT_PROGRESS_BAR = None

    _print_import_progress(
        ImportProgress(
            phase="conversations",
            current=1,
            total=2,
            completed=0,
            detail="General",
        )
    )
    bar = cli._IMPORT_PROGRESS_BAR
    assert bar is not None

    _print_import_progress(ImportProgress(phase="refresh", mode="full"))

    assert bar.closed is True
    assert cli._IMPORT_PROGRESS_BAR is None
    assert "Import refresh: mode=full." in capsys.readouterr().out


def test_import_cli_auto_initializes_new_archive(tmp_path: Path, capsys) -> None:
    archive_path = tmp_path / "archive"
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord-secret
  guild_id: 123
""",
        encoding="utf-8",
    )

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    runtime.import_to_archive.return_value = type(
        "Report",
        (),
        dict(identities=1, conversations=1, messages=1, attachments=0),
    )()
    registry = MagicMock()
    registry.create.return_value = runtime
    registry.build_config.return_value = type(
        "DiscordConfig",
        (),
        {"token": "discord-secret"},
    )()

    with patch(
        "archive_sync_engine.cli.default_source_runtime_registry",
        return_value=registry,
    ):
        assert main(["import", "--config", str(config)]) == 0

    paths = ArchivePaths(archive_path.resolve())
    assert paths.database.is_file()
    assert paths.manifest.is_file()
    assert "Initialized Archive Package:" in capsys.readouterr().out


def test_import_cli_rejects_nonempty_uninitialized_archive(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    archive_path.mkdir()
    (archive_path / "unexpected.txt").write_text("not an archive", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord-secret
  guild_id: 123
""",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        main(["import", "--config", str(config)])

    assert not (archive_path / "archive.sqlite").exists()
    assert not (archive_path / "manifest.json").exists()


def test_import_cli_reports_existing_archive_conversation_conflict_with_resume_guidance(
    tmp_path: Path,
    capsys,
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
""",
        encoding="utf-8",
    )

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    runtime.import_to_archive.side_effect = ValueError(
        "Import preflight detected existing Archive conversations: conversation-001. "
        "A full import cannot recreate conversations already present in the Archive. "
        "If this is an existing Archive that you want to refresh, rerun with --resume."
    )
    registry = MagicMock()
    registry.create.return_value = runtime

    with patch("archive_sync_engine.cli.default_source_runtime_registry", return_value=registry):
        with pytest.raises(SystemExit) as exc_info:
            main(["import", "--config", str(config)])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "Import preflight detected existing Archive conversations: conversation-001." in captured.err
    assert "rerun with --resume" in captured.err


def test_import_cli_reports_connection_and_phase_status(tmp_path: Path, capsys) -> None:
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
delays:
  between_messages_seconds: 0.5
  between_channels_seconds: 2.0
""",
        encoding="utf-8",
    )

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    runtime.import_to_archive.return_value = type(
        "Report",
        (),
        dict(identities=1, conversations=1, messages=2, attachments=0),
    )()
    registry = MagicMock()
    registry.create.return_value = runtime

    with patch("archive_sync_engine.cli.default_source_runtime_registry", return_value=registry):
        assert main(["import", "--config", str(config)]) == 0

    output = capsys.readouterr().out
    assert "Attempting to connect to source adapter 'discord'" in output
    assert "Connected successfully." in output
    assert "Initiating phase: import discord → Archive." in output
    assert "Import completed: 1 identities, 1 conversations, 2 messages, 0 attachments." in output
    call = runtime.import_to_archive.call_args
    assert call.kwargs["between_messages_seconds"] == 0.5
    assert call.kwargs["between_channels_seconds"] == 2.0


def test_sync_invocation_translates_platform_cli_flags_at_boundary() -> None:
    from archive_sync_engine.cli import _sync_invocation_from_args, _SyncInvocation

    args = build_parser().parse_args([
        "sync",
        "--input-adapter", "discord",
        "--input-scope", "123",
        "--destination-adapter", "fluxer",
        "--destination-scope", "456",
        "--discord-token", "discord-secret",
        "--fluxer-token", "fluxer-secret",
        "--fluxer-api-url", "https://example.test",
        "--fluxer-max-retries", "7",
    ])

    invocation = _sync_invocation_from_args(args)

    assert isinstance(invocation, _SyncInvocation)
    assert invocation.input_adapter == "discord"
    assert invocation.destination_adapter == "fluxer"
    assert invocation.input_scope == ("123",)
    assert invocation.destination_scope == ("456",)
    assert invocation.adapter_config_overrides["discord"]["token"] == "discord-secret"
    assert invocation.adapter_config_overrides["fluxer"]["token"] == "fluxer-secret"
    assert invocation.adapter_config_overrides["fluxer"]["api_url"] == "https://example.test"
    assert invocation.adapter_config_overrides["fluxer"]["max_retries"] == 7


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

    registry = MagicMock()
    registry.create.return_value = runtime
    with patch("archive_sync_engine.cli.default_sync_runtime_registry", return_value=registry):
        result = main(
            [
                "sync", "--discord-token", "discord-token", "--discord-guild-id", "10",
                "--fluxer-token", "fluxer-token", "--fluxer-guild-id", "guild-1",
                "--archive", str(archive_path), "--resume",
            ]
        )

    assert result == 0
    registry.create.assert_called_once()
    request = registry.create.call_args.args[2]
    assert request.input_adapter == "discord"
    assert request.input_scope == ("10",)
    assert request.destination_adapter == "fluxer"
    assert request.destination_scope == ("guild-1",)
    runtime.run.assert_called_once_with(resume_import=True)
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
    registry = MagicMock()
    registry.create.return_value = runtime
    with patch("archive_sync_engine.cli.default_sync_runtime_registry", return_value=registry):
        assert main([
            "sync", "--discord-token", "discord-token", "--discord-guild-id", "10",
            "--fluxer-token", "fluxer-token", "--fluxer-guild-id", "guild-1",
            "--archive", str(archive_path), "--fluxer-identity", "bot-user",
        ]) == 0
    request = registry.create.call_args.args[2]
    mappings = request.adapter_config["identity_mappings"]
    assert mappings[0].username == "bot-user"
    assert mappings[0].fluxer_auth_key is None

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
    registry = MagicMock()
    registry.create.return_value = runtime
    with patch("archive_sync_engine.cli.default_sync_runtime_registry", return_value=registry):
        assert main([
            "sync", "--discord-token", "discord-cli", "--discord-guild-id", "10",
            "--fluxer-token", "fluxer-cli", "--fluxer-guild-id", "guild-cli",
            "--archive", str(archive_path),
        ]) == 0
    request = registry.create.call_args.args[2]
    assert request.adapter_config["discord"].token == "discord-cli"
    assert request.adapter_config["fluxer"].token == "fluxer-cli"
    assert request.destination_scope == ("guild-cli",)

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
            direction=RunDirection.SYNC, input_adapter="discord", input_scope=("10", "20"),
            destination_adapter="fluxer", destination_scope=("fluxer-guild",),
        )
    )
    from archive_sync_engine.sync.session import SyncDirection, SyncSession
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    ArchivePackage(ArchivePaths(archive_path)).save_session(
        SyncSession(id="sync-1", direction=SyncDirection.EXPORT, started_at=now, updated_at=now)
    )
    config = tmp_path / "config.yaml"
    config.write_text("""
archive:
  path: ./archive
discord:
  token: discord-secret
  guild_id: 999
fluxer:
  token: fluxer-secret
  server_id: config-guild
""", encoding="utf-8")
    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    registry = MagicMock()
    registry.create.return_value = runtime
    with patch("archive_sync_engine.cli.default_sync_runtime_registry", return_value=registry):
        assert main(["resume", "--config", str(config)]) == 0
    request = registry.create.call_args.args[2]
    assert request.input_scope == ("10", "20")
    assert request.destination_scope == ("fluxer-guild",)
    assert request.adapter_config["discord"].guild_ids == (10, 20)
    assert request.adapter_config["fluxer"].token == "fluxer-secret"
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
    registry = MagicMock()
    registry.create.return_value = runtime
    with patch("archive_sync_engine.cli.default_sync_runtime_registry", return_value=registry):
        assert main([
            "sync", "--discord-token", "discord-token", "--discord-guild-id", "10",
            "--fluxer-token", "fluxer-token", "--fluxer-guild-id", "guild-1",
            "--archive", str(archive_path), "--dry-run",
        ]) == 0
    runtime.dry_run.assert_called_once_with()
    runtime.run.assert_not_called()
    assert not (archive_path / "run.json").exists()

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
    assert "fluxer\ttrue\ttrue" in output


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
    registry.build_config.return_value = type("DiscordConfig", (), {"token": "discord-secret"})()

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
    runtime.import_to_archive.assert_called_once()
    import_call = runtime.import_to_archive.call_args
    assert import_call.args == (ArchivePaths(archive_path.resolve()),)
    assert import_call.kwargs["resume"] is False
    assert callable(import_call.kwargs["on_status"])

    persisted = ArchivePackage(ArchivePaths(archive_path)).load_run_configuration()
    assert persisted.direction is RunDirection.IMPORT
    assert persisted.input_adapter == "discord"
    assert persisted.input_scope == ("123",)
    assert persisted.destination_adapter is None
    assert persisted.destination_scope == ()


def test_import_cli_reports_archive_counts_after_successful_import(
    tmp_path: Path,
    capsys,
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
""",
        encoding="utf-8",
    )

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    runtime.import_to_archive.return_value = type(
        "ImportReport",
        (),
        {
            "identities": 4,
            "conversations": 2,
            "messages": 17,
            "attachments": 3,
        },
    )()

    registry = MagicMock()
    registry.create.return_value = runtime
    registry.build_config.return_value = type(
        "DiscordConfig",
        (),
        {"token": "discord-secret"},
    )()

    with patch(
        "archive_sync_engine.cli.default_source_runtime_registry",
        return_value=registry,
    ):
        assert main(["import", "--config", str(config)]) == 0

    output = capsys.readouterr().out
    assert "Attempting to connect to source adapter 'discord'" in output
    assert "Connected successfully." in output
    assert "Initiating phase: import discord → Archive." in output
    assert "Import completed: 4 identities, 2 conversations, 17 messages, 3 attachments." in output


def test_import_cli_resume_allows_incomplete_reply_references(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "archive"
    paths = ArchivePaths(archive_path)
    ArchivePackage.initialize(paths)
    package = ArchivePackage(paths)
    package.save_run_configuration(
        SyncRunConfiguration(
            direction=RunDirection.IMPORT,
            input_adapter="discord",
            input_scope=("10",),
        )
    )

    from archive_sync_engine.importer import ImportState
    from archive_sync_engine.sync.session import SyncDirection, SyncSession
    from datetime import datetime, timezone
    import sqlite3

    package.save_import_state(
        ImportState(
            payload={
                "conversation_id": "discord:guild:123:channel:10",
                "message_id": "discord:message:200",
            }
        )
    )
    now = datetime.now(timezone.utc)
    package.save_session(
        SyncSession(
            id="import-session",
            direction=SyncDirection.IMPORT,
            started_at=now,
            updated_at=now,
            error="interrupted",
        )
    )

    with sqlite3.connect(paths.database) as connection:
        connection.execute(
            "INSERT INTO identities (identity_key, display_name) VALUES (?, ?)",
            ("discord:user:1", "Alice"),
        )
        connection.execute(
            "INSERT INTO conversations (conversation_id, conversation_type, title, parent_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "discord:guild:123:channel:10",
                "channel",
                "general",
                None,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO messages (message_id, conversation_id, identity_key, created_at, edited_at, reply_to_message_id, content) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "discord:message:200",
                "discord:guild:123:channel:10",
                "discord:user:1",
                "2026-01-01T00:00:00+00:00",
                None,
                "discord:message:199",
                "reply content",
            ),
        )

    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: current-discord-secret
  guild_id: 10
""",
        encoding="utf-8",
    )

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    runtime.import_to_archive.return_value = type(
        "Report",
        (),
        dict(identities=1, conversations=1, messages=1, attachments=0),
    )()
    registry = MagicMock()
    registry.create.return_value = runtime
    registry.build_config.return_value = type(
        "DiscordConfig", (), {"token": "current-discord-secret"}
    )()

    with patch("archive_sync_engine.cli.default_source_runtime_registry", return_value=registry):
        assert main(["import", "--config", str(config), "--resume"]) == 0

    runtime.import_to_archive.assert_called_once()
    assert runtime.import_to_archive.call_args.kwargs["resume"] is True


def test_import_cli_resume_accepts_discovery_checkpoint_without_import_state(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "archive"
    paths = ArchivePaths(archive_path)
    ArchivePackage.initialize(paths)
    package = ArchivePackage(paths)
    package.save_run_configuration(
        SyncRunConfiguration(
            direction=RunDirection.IMPORT,
            input_adapter="discord",
            input_scope=("10",),
        )
    )
    from archive_sync_engine.importer import DiscoveryState
    from archive_sync_engine.sync.session import SyncDirection, SyncSession
    from datetime import datetime, timezone

    package.save_discovery_state(DiscoveryState.identities_started())
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
  guild_id: 10
""",
        encoding="utf-8",
    )

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    runtime.import_to_archive.return_value = type(
        "Report",
        (),
        dict(identities=1, conversations=0, messages=0, attachments=0),
    )()
    registry = MagicMock()
    registry.create.return_value = runtime
    registry.build_config.return_value = type(
        "DiscordConfig", (), {"token": "current-discord-secret"}
    )()

    with patch("archive_sync_engine.cli.default_source_runtime_registry", return_value=registry):
        assert main(["import", "--config", str(config), "--resume"]) == 0

    runtime.import_to_archive.assert_called_once()
    assert runtime.import_to_archive.call_args.kwargs["resume"] is True


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
    registry.build_config.return_value = type("DiscordConfig", (), {"token": "current-discord-secret"})()

    with patch(
        "archive_sync_engine.cli.default_source_runtime_registry",
        return_value=registry,
    ):
        assert main(["resume", "--config", str(config)]) == 0

    request = registry.create.call_args.args[1]
    assert request.adapter == "discord"
    assert request.scope == ("10", "20")
    assert request.adapter_config["discord"].token == "current-discord-secret"
    runtime.import_to_archive.assert_called_once()
    import_call = runtime.import_to_archive.call_args
    assert import_call.args == (ArchivePaths(archive_path.resolve()),)
    assert import_call.kwargs["resume"] is True



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
delays:
  between_messages_seconds: 0.75
  between_channels_seconds: 3.0
""",
        encoding="utf-8",
    )

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    runtime.adapter = object()

    registry = MagicMock()
    registry.create.return_value = runtime
    registry.build_config.return_value = {"fluxer": type("FluxerConfig", (), {"token": "fluxer-secret"})()}

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
    assert exporter.export.call_args.kwargs["between_messages_seconds"] == 0.75
    assert exporter.export.call_args.kwargs["between_channels_seconds"] == 3.0
    assert isinstance(exporter.export.call_args.kwargs["state_repository"], SQLiteStateRepository)


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
    registry.build_config.return_value = {"fluxer": type("FluxerConfig", (), {"token": "fluxer-secret"})()}

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


def test_init_cli_creates_archive_from_explicit_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    archive_path = tmp_path / "archive"

    assert main(["init", "--archive", str(archive_path)]) == 0

    output = capsys.readouterr().out
    assert "Initialized Archive Package:" in output
    report = validate_archive_package(ArchivePaths(archive_path))
    assert report.valid


def test_init_cli_creates_archive_from_configuration(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = tmp_path / "config.yaml"
    archive_path = tmp_path / "configured-archive"
    config_path.write_text(
        """
archive:
  path: ./configured-archive
discord:
  token: discord-token
  guild_id: \"123\"
fluxer:
  token: fluxer-token
  server_id: fluxer-server
""".strip() + "\n",
        encoding="utf-8",
    )

    assert main(["init", "--config", str(config_path)]) == 0

    output = capsys.readouterr().out
    assert str(config_path) in output
    assert validate_archive_package(ArchivePaths(archive_path)).valid


def test_init_cli_config_does_not_resolve_credentials(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    archive_path = tmp_path / "archive"
    config_path.write_text(
        """
archive:
  path: ./archive
discord:
  token_file: missing-discord.token
  guild_id: \"123\"
fluxer:
  token_file: missing-fluxer.token
  server_id: fluxer-server
""".strip() + "\n",
        encoding="utf-8",
    )

    assert main(["init", "--config", str(config_path)]) == 0
    assert validate_archive_package(ArchivePaths(archive_path)).valid


def test_init_cli_refuses_non_empty_directory(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    archive_path.mkdir()
    (archive_path / "existing.txt").write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(SystemExit):
        main(["init", "--archive", str(archive_path)])

    assert (archive_path / "existing.txt").read_text(encoding="utf-8") == "do not overwrite"


def test_config_example_cli_writes_template(tmp_path: Path, capsys) -> None:
    output = tmp_path / "config.yaml"

    assert main(["config-example", "--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8") == (
        Path("config-example.yaml").read_text(encoding="utf-8")
    )
    assert f"Configuration template written to: {output}" in capsys.readouterr().out


def test_config_example_cli_refuses_to_overwrite_existing_file(
    tmp_path: Path,
) -> None:
    output = tmp_path / "config.yaml"
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(SystemExit):
        main(["config-example", "--output", str(output)])

    assert output.read_text(encoding="utf-8") == "existing"


def test_config_example_cli_force_overwrites_existing_file(tmp_path: Path) -> None:
    output = tmp_path / "config.yaml"
    output.write_text("existing", encoding="utf-8")

    assert main(["config-example", "--output", str(output), "--force"]) == 0
    assert output.read_text(encoding="utf-8") == Path(
        "config-example.yaml"
    ).read_text(encoding="utf-8")

def test_export_cli_does_not_require_discord_credentials(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
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
    registry.build_config.return_value = {
        "fluxer": MagicMock(token="fluxer-secret"),
        "identity_mappings": (),
    }

    with (
        patch(
            "archive_sync_engine.cli.default_destination_runtime_registry",
            return_value=registry,
        ),
        patch("archive_sync_engine.cli.CanonicalExporter"),
    ):
        assert main(["export", "--config", str(config)]) == 0

    registry.build_config.assert_called_once()
    request = registry.create.call_args.args[1]
    assert request.adapter_config["fluxer"].token == "fluxer-secret"


def test_adapters_cli_text_reports_registered_runtime_implementations(capsys) -> None:
    assert main(["adapters"]) == 0
    output = capsys.readouterr().out
    assert "REGISTERED SOURCE RUNTIMES" in output
    assert "discord" in output
    assert "REGISTERED DESTINATION RUNTIMES" in output
    assert "fluxer" in output
    assert "REGISTERED SYNC RUNTIMES" in output
    assert "discord\tfluxer" in output


def test_adapters_cli_json_is_machine_readable_with_runtime_implementations(capsys) -> None:
    import json

    assert main(["adapters", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source_runtimes"] == ["discord", "fluxer"]
    assert payload["destination_runtimes"] == ["fluxer"]
    assert payload["sync_runtimes"] == [{"input_adapter": "discord", "destination_adapter": "fluxer"}]


def test_adapters_cli_validates_registered_capabilities(capsys) -> None:
    assert main(["adapters", "--validate"]) == 0
    assert "Adapter capability validation: OK" in capsys.readouterr().out


def test_adapters_cli_json_validates_registered_capabilities(capsys) -> None:
    import json

    assert main(["adapters", "--validate", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"errors": [], "valid": True}


def test_preflight_reports_adapter_capabilities(tmp_path: Path, capsys) -> None:
    (tmp_path / "discord.token").write_text("discord-secret\n", encoding="utf-8")
    (tmp_path / "fluxer.token").write_text("fluxer-secret\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("""
archive:
  path: ./archive
discord:
  token_file: discord.token
  guild_id: 123
fluxer:
  token_file: fluxer.token
  server_id: fluxer-server
""", encoding="utf-8")
    ArchivePackage.initialize(ArchivePaths(tmp_path / "archive"))

    assert main(["preflight", "--config", str(config), "--json"]) == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    assert payload["adapter_capabilities"] == {"errors": [], "valid": True}


def test_preflight_fails_when_adapter_capabilities_are_invalid(tmp_path: Path, capsys, monkeypatch) -> None:
    (tmp_path / "discord.token").write_text("discord-secret\n", encoding="utf-8")
    (tmp_path / "fluxer.token").write_text("fluxer-secret\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("""
archive:
  path: ./archive
discord:
  token_file: discord.token
  guild_id: 123
fluxer:
  token_file: fluxer.token
  server_id: fluxer-server
""", encoding="utf-8")
    ArchivePackage.initialize(ArchivePaths(tmp_path / "archive"))
    from archive_sync_engine.adapters.capability_validation import AdapterCapabilityReport
    monkeypatch.setattr(
        "archive_sync_engine.adapters.capability_validation.validate_adapter_capabilities",
        lambda: AdapterCapabilityReport(("broken registration",)),
    )

    assert main(["preflight", "--config", str(config), "--json"]) == 1
    import json
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is False
    assert payload["adapter_capabilities"]["errors"] == ["broken registration"]


def test_sync_cli_uses_generic_adapter_and_scope_options(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    registry = MagicMock()
    registry.create.return_value = runtime

    with patch("archive_sync_engine.cli.default_sync_runtime_registry", return_value=registry):
        assert main(
            [
                "sync",
                "--input-adapter", "discord",
                "--input-scope", "10",
                "--destination-adapter", "fluxer",
                "--destination-scope", "destination-scope",
                "--discord-token", "discord-token",
                "--fluxer-token", "fluxer-token",
                "--archive", str(archive_path),
            ]
        ) == 0

    request = registry.create.call_args.args[2]
    assert request.input_adapter == "discord"
    assert request.input_scope == ("10",)
    assert request.destination_adapter == "fluxer"
    assert request.destination_scope == ("destination-scope",)


def test_sync_resume_uses_persisted_adapter_and_scope_at_runtime_boundary(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))
    package = ArchivePackage(ArchivePaths(archive_path))
    package.save_run_configuration(
        SyncRunConfiguration(
            direction=RunDirection.SYNC,
            input_adapter="discord",
            input_scope=("10",),
            destination_adapter="fluxer",
            destination_scope=("persisted-destination",),
        )
    )
    from archive_sync_engine.sync.session import SyncDirection, SyncSession
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    package.save_session(
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
  server_id: configured-destination
""",
        encoding="utf-8",
    )

    runtime = MagicMock()
    runtime.__enter__.return_value = runtime
    runtime.__exit__.return_value = None
    registry = MagicMock()
    registry.create.return_value = runtime

    with patch("archive_sync_engine.cli.default_sync_runtime_registry", return_value=registry):
        assert main(["resume", "--config", str(config)]) == 0

    request = registry.create.call_args.args[2]
    assert request.input_scope == ("10",)
    assert request.destination_scope == ("persisted-destination",)
    # The persisted scope is opaque at the generic boundary. The current
    # Discord runtime's concrete config still owns its platform interpretation.
    assert request.adapter_config["discord"].guild_ids == (10,)


def test_preflight_can_validate_only_selected_source_adapter(tmp_path: Path, capsys) -> None:
    (tmp_path / "discord.token").write_text("discord-secret\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token_file: discord.token
  guild_id: 123
user_mappings:
  discord:
    "123456789":
      fluxer_username: BobOnFluxer
""",
        encoding="utf-8",
    )
    ArchivePackage.initialize(ArchivePaths(tmp_path / "archive"))

    assert main([
        "preflight",
        "--config", str(config),
        "--input-adapter", "discord",
    ]) == 0

    output = capsys.readouterr().out
    assert "Input adapter: discord" in output
    assert "Credentials: RESOLVED" in output



def test_preflight_source_only_does_not_validate_unused_fluxer_mappings(
    tmp_path: Path, capsys
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
discord:
  token: discord-secret
  guild_id: 123
user_mappings:
  discord:
    "123":
      fluxer_username: InvalidFluxerName
      fluxer_auth_key: fluxer-secret
""",
        encoding="utf-8",
    )
    ArchivePackage.initialize(ArchivePaths(tmp_path / "archive"))

    assert main(["preflight", "--config", str(config)]) == 0
    assert "Configuration: VALID" in capsys.readouterr().out

def test_config_example_documents_discord_bot_configuration() -> None:
    from pathlib import Path

    example = (Path(__file__).resolve().parents[2] / "config-example.yaml").read_text(
        encoding="utf-8"
    )

    assert "Discord bot account" in example
    assert 'token_file: "discord_bot.token"' in example
    assert "YOUR_DISCORD_BOT_TOKEN" in example


def test_cli_expected_application_error_does_not_print_usage(capsys, tmp_path: Path) -> None:
    config = tmp_path / "missing.yaml"

    with pytest.raises(SystemExit) as exc_info:
        main(["import", "--config", str(config)])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "usage:" not in captured.err
    assert "archive-sync-engine: error:" in captured.err


def test_cli_capability_error_is_reported_as_expected_error(capsys, monkeypatch) -> None:
    def fail(_args):
        from archive_sync_engine.adapters.exceptions import CapabilityError

        raise CapabilityError(
            "Fluxer reaction synchronization requires an identity mapping "
            "for reaction actor discord:user:123."
        )

    monkeypatch.setattr("archive_sync_engine.cli._run_export", fail)

    with pytest.raises(SystemExit) as exc_info:
        main(["export", "--config", "/tmp/archive-sync-engine-test.yaml"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "usage:" not in captured.err
    assert "archive-sync-engine: error: Fluxer reaction synchronization" in captured.err
    assert "Unexpected application error" not in captured.err


def test_cli_unexpected_application_error_does_not_print_usage(capsys, monkeypatch) -> None:
    def fail(_args):
        raise RuntimeError("boom")

    monkeypatch.setattr("archive_sync_engine.cli._run_validate", fail)

    with pytest.raises(SystemExit) as exc_info:
        main(["validate", "--archive", "/tmp/archive-sync-engine-test-missing"] )

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "usage:" not in captured.err
    assert "Unexpected application error" in captured.err

def test_export_cli_reports_connection_and_phase_status(tmp_path: Path, capsys) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))
    config = tmp_path / "config.yaml"
    config.write_text(
        """
archive:
  path: ./archive
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
    registry.build_config.return_value = {
        "fluxer": type("FluxerConfig", (), {"token": "fluxer-secret"})()
    }

    exporter = MagicMock()
    exporter.export.return_value = type("Report", (), {"executed_operations": 3})()

    from archive_sync_engine.sync.progress import SyncProgress
    exporter.export.side_effect = lambda **kwargs: (
        kwargs["on_status"](SyncProgress("conversations", 1, detail="conversation-1")),
        type("Report", (), {"executed_operations": 3})(),
    )[1]

    with (
        patch("archive_sync_engine.cli.default_destination_runtime_registry", return_value=registry),
        patch("archive_sync_engine.cli.CanonicalExporter", return_value=exporter),
    ):
        assert main(["export", "--config", str(config)]) == 0

    output = capsys.readouterr().out
    assert "Attempting to connect to destination adapter 'fluxer'" in output
    assert "Connected successfully." in output
    assert "Initiating phase: export Archive → fluxer." in output
    assert "Exporting conversations 1: conversation-1..." in output
    assert "Export completed: 3 operations." in output



def test_tag_cli_create_list_show_and_range(tmp_path: Path, capsys) -> None:
    archive_path = tmp_path / "archive"
    ArchivePackage.initialize(ArchivePaths(archive_path))

    assert main(["tag", "create", "--archive", str(archive_path), "--name", "Discord Export v1, 2026-10-13"]) == 0
    assert main(["tag", "create", "--archive", str(archive_path), "--name", "Discord Export v2, 2026-11-01"]) == 0
    capsys.readouterr()

    assert main(["tag", "list", "--archive", str(archive_path)]) == 0
    output = capsys.readouterr().out
    assert "Discord Export v1, 2026-10-13" in output
    assert "Discord Export v2, 2026-11-01" in output

    assert main(["tag", "range", "--archive", str(archive_path), "--start", "Discord Export v1, 2026-10-13", "--end", "Discord Export v2, 2026-11-01"]) == 0
    assert capsys.readouterr().out == ""

    assert main(["tag", "range", "--archive", str(archive_path), "--start", "Discord Export v1, 2026-10-13", "--end", "Discord Export v2, 2026-11-01", "--inclusive"]) == 0
    output = capsys.readouterr().out
    assert "1\tDiscord Export v1, 2026-10-13" in output
    assert "2\tDiscord Export v2, 2026-11-01" in output

    assert main(["tag", "show", "--archive", str(archive_path), "Discord Export v1, 2026-10-13"]) == 0
    output = capsys.readouterr().out
    assert "Name: Discord Export v1, 2026-10-13" in output
    assert "Sequence: 1" in output
