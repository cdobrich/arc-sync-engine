"""Command-line entry point for Archive-Sync Engine."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from archive_sync_engine.logging_support import (
    configure_logging,
    report_expected_error,
    report_unexpected_error,
)

from archive_sync_engine.adapters import (
    DestinationRuntimeRequest,
    SourceRuntimeRequest,
    default_adapter_registry,
    default_destination_runtime_registry,
    default_source_runtime_registry,
    default_sync_pair_registry,
)
from archive_sync_engine.sync.runtime_registry import default_sync_runtime_registry
from archive_sync_engine.adapters.discord.runtime import DiscordClientConfig
from archive_sync_engine.adapters.fluxer import FluxerIdentityMapping
from archive_sync_engine.adapters.fluxer_runtime import FluxerClientConfig
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.package import ArchivePackage
from archive_sync_engine.config import ConfigurationError, load_setup_configuration
from archive_sync_engine.archive import Archive, validate_archive_package
from archive_sync_engine.exporter import CanonicalExporter
from archive_sync_engine.repository.sqlite_state_repository import SQLiteStateRepository
from archive_sync_engine.sync.run_configuration import RunDirection, SyncRunConfiguration
from archive_sync_engine.sync.runtime_request import SyncRuntimeRequest
from archive_sync_engine.sync.discord_fluxer_runtime import (
    DiscordFluxerSyncConfig,
    DiscordFluxerSyncRuntime,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="archive-sync-engine",
        description="Archive and synchronize Discord messages to Fluxer.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_logging_options(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--log-level",
            choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
            default="WARNING",
            help="Application log level (default: WARNING).",
        )
        command.add_argument(
            "--log-file",
            type=Path,
            default=None,
            help="Optional file for application logs and error details.",
        )

    import_command = subparsers.add_parser(
        "import",
        help="Import a configured source into an Archive Package.",
    )
    import_command.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Human-authored YAML setup configuration.",
    )
    import_command.add_argument(
        "--input-adapter",
        default="discord",
        help="Registered source adapter to import from (default: discord).",
    )
    import_command.add_argument(
        "--input-scope",
        action="append",
        default=[],
        help="Opaque source scope value; repeat as needed to override configuration.",
    )
    import_command.add_argument(
        "--archive",
        type=Path,
        default=None,
        help="Archive Package directory (overrides --config).",
    )
    import_command.add_argument(
        "--resume",
        action="store_true",
        help="Resume the persisted importer-owned checkpoint state.",
    )
    add_logging_options(import_command)

    export_command = subparsers.add_parser(
        "export",
        help="Export an existing Archive Package to a registered destination adapter.",
    )
    export_command.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Human-authored YAML setup configuration.",
    )
    export_command.add_argument(
        "--destination-adapter",
        default="fluxer",
        help="Registered destination adapter to export to (default: fluxer).",
    )
    export_command.add_argument(
        "--destination-scope",
        action="append",
        default=[],
        help="Opaque destination scope value; repeat as needed to override configuration.",
    )
    export_command.add_argument(
        "--archive",
        type=Path,
        default=None,
        help="Archive Package directory (overrides --config).",
    )
    export_command.add_argument(
        "--fluxer-api-url",
        default=None,
        help="Optional Fluxer API URL for self-hosted deployments.",
    )
    export_command.add_argument(
        "--fluxer-max-retries",
        type=int,
        default=4,
        help="Maximum Fluxer REST retries (default: 4).",
    )
    add_logging_options(export_command)

    init_command = subparsers.add_parser(
        "init",
        help="Create a new empty Archive Package for a configured or explicit path.",
    )
    init_group = init_command.add_mutually_exclusive_group(required=True)
    init_group.add_argument(
        "--config",
        type=Path,
        help="Human-authored YAML setup configuration whose archive.path selects the package.",
    )
    init_group.add_argument(
        "--archive",
        type=Path,
        help="Archive Package directory to initialize.",
    )
    add_logging_options(init_command)

    sync = subparsers.add_parser(
        "sync",
        help="Import Discord into an Archive Package and synchronize it to Fluxer.",
    )
    sync.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Human-authored YAML setup configuration.",
    )
    sync.add_argument(
        "--discord-token",
        default=None,
        help="Discord authentication token (overrides --config).",
    )
    sync.add_argument(
        "--discord-guild-id",
        action="append",
        type=int,
        required=False,
        help="Discord guild ID to archive. Repeat for multiple guilds; overrides --config.",
    )
    sync.add_argument(
        "--fluxer-token",
        default=None,
        help="Fluxer bot authentication token (overrides --config).",
    )
    sync.add_argument(
        "--fluxer-guild-id",
        default=None,
        help="Target Fluxer guild ID (overrides --config).",
    )
    sync.add_argument(
        "--archive",
        type=Path,
        default=None,
        help="Archive Package directory (overrides --config).",
    )
    sync.add_argument(
        "--fluxer-api-url",
        default=None,
        help="Optional Fluxer API URL for self-hosted deployments.",
    )
    sync.add_argument(
        "--fluxer-max-retries",
        type=int,
        default=4,
        help="Maximum Fluxer REST retries (default: 4).",
    )
    sync.add_argument(
        "--resume",
        action="store_true",
        help="Resume the previous Discord import checkpoint.",
    )
    sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan synchronization without importing, executing, or changing state.",
    )
    sync.add_argument(
        "--fluxer-identity",
        action="append",
        default=[],
        metavar="USERNAME[:AUTH_TOKEN]",
        help=(
            "Map a canonical identity to a Fluxer actor. Repeat as needed. "
            "Omit AUTH_TOKEN to use the bot account for that identity."
        ),
    )
    add_logging_options(sync)

    resume = subparsers.add_parser(
        "resume",
        help="Resume the persisted Archive synchronization/import run.",
    )
    resume.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Human-authored YAML setup configuration containing credentials.",
    )
    resume.add_argument(
        "--archive",
        type=Path,
        default=None,
        help="Archive Package directory (overrides config.yaml).",
    )
    add_logging_options(resume)

    preflight = subparsers.add_parser(
        "preflight",
        help="Validate configuration, credentials, and Archive readiness without executing work.",
    )
    preflight.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Human-authored YAML setup configuration.",
    )
    preflight.add_argument(
        "--archive",
        type=Path,
        default=None,
        help="Archive Package directory (overrides --config).",
    )
    preflight.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON instead of text.",
    )
    add_logging_options(preflight)

    validate = subparsers.add_parser(
        "validate",
        help="Validate the integrity of an Archive Package.",
    )
    validate.add_argument(
        "--archive",
        type=Path,
        required=True,
        help="Archive Package directory to validate.",
    )
    validate.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON instead of text.",
    )
    add_logging_options(validate)

    adapters = subparsers.add_parser(
        "adapters",
        help="List adapter roles registered with the application.",
    )
    adapters.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON.",
    )
    add_logging_options(adapters)

    diagnostics = subparsers.add_parser(
        "diagnostics",
        help="Inspect successfully checkpointed synchronization executions.",
    )
    diagnostics.add_argument(
        "--archive",
        type=Path,
        required=True,
        help="Archive Package directory containing synchronization.sqlite.",
    )
    diagnostics.add_argument(
        "--canonical-id",
        default=None,
        help="Filter executions to one canonical entity ID.",
    )
    diagnostics.add_argument(
        "--operation-type",
        default=None,
        help="Filter executions by operation class name.",
    )
    diagnostics.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of records to display (default: 100).",
    )
    diagnostics.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON instead of tabular text.",
    )
    diagnostics.add_argument(
        "--summary",
        action="store_true",
        help="Inspect Archive integrity and persisted run/session state instead of execution records.",
    )
    add_logging_options(diagnostics)
    return parser


def _require_supported_sync_pair(input_adapter: str, destination_adapter: str) -> None:
    """Validate a source/destination pair through the application registry."""
    try:
        default_sync_pair_registry().get(input_adapter, destination_adapter)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc


def _parse_identity_mappings(values: Sequence[str]) -> tuple[FluxerIdentityMapping, ...]:
    mappings: list[FluxerIdentityMapping] = []
    for value in values:
        username, separator, auth_token = value.partition(":")
        if not username:
            raise ValueError("Fluxer identity mapping username must not be empty.")
        mappings.append(
            FluxerIdentityMapping(
                username=username,
                fluxer_auth_key=auth_token if separator else None,
            )
        )
    return tuple(mappings)


def _run_adapters(args: argparse.Namespace) -> int:
    """List registered adapter roles and concrete synchronization pairs."""
    descriptors = default_adapter_registry().list()
    pairs = default_sync_pair_registry().list()
    if args.as_json:
        import json

        print(
            json.dumps(
                {
                    "adapters": [
                        {
                            "name": descriptor.name,
                            "source": descriptor.source,
                            "destination": descriptor.destination,
                            "description": descriptor.description,
                        }
                        for descriptor in descriptors
                    ],
                    "sync_pairs": [
                        {
                            "input_adapter": pair.input_adapter,
                            "destination_adapter": pair.destination_adapter,
                            "description": pair.description,
                        }
                        for pair in pairs
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print("NAME\tSOURCE\tDESTINATION\tDESCRIPTION")
        for descriptor in descriptors:
            print(
                f"{descriptor.name}\t"
                f"{str(descriptor.source).lower()}\t"
                f"{str(descriptor.destination).lower()}\t"
                f"{descriptor.description}"
            )
        print("\nSUPPORTED SYNC PAIRS")
        print("INPUT\tDESTINATION\tDESCRIPTION")
        for pair in pairs:
            print(
                f"{pair.input_adapter}\t{pair.destination_adapter}\t"
                f"{pair.description}"
            )
    return 0


def _run_diagnostics(args: argparse.Namespace) -> int:
    if args.summary:
        return _run_diagnostics_summary(args)

    repository_path = args.archive / "synchronization.sqlite"
    with SQLiteStateRepository(repository_path) as repository:
        entries = repository.query_execution_log(
            canonical_id=args.canonical_id,
            operation_type=args.operation_type,
            limit=args.limit,
        )

    if args.as_json:
        import json

        print(
            json.dumps(
                [
                    {
                        "id": entry.id,
                        "operation_type": entry.operation_type,
                        "canonical_id": entry.canonical_id,
                        "deleted": entry.deleted,
                        "deleted_entity": (
                            entry.deleted_entity.value
                            if entry.deleted_entity is not None
                            else None
                        ),
                    }
                    for entry in entries
                ],
                sort_keys=True,
            )
        )
    else:
        print("ID\tOPERATION\tCANONICAL_ID\tDELETED\tDELETED_ENTITY")
        for entry in entries:
            print(
                f"{entry.id}\t{entry.operation_type}\t"
                f"{entry.canonical_id or ''}\t{str(entry.deleted).lower()}\t"
                f"{entry.deleted_entity.value if entry.deleted_entity is not None else ''}"
            )

    return 0



def _run_diagnostics_summary(args: argparse.Namespace) -> int:
    """Inspect read-only Archive and operational state without executing work."""
    paths = ArchivePaths(args.archive.expanduser().resolve())
    integrity = validate_archive_package(paths)

    summary: dict[str, object] = {
        "archive": {
            "path": str(paths.root),
            "valid": integrity.valid,
            "errors": list(integrity.errors),
            "conversations": integrity.conversations_checked,
            "identities": integrity.identities_checked,
            "messages": integrity.messages_checked,
            "attachments": integrity.attachments_checked,
            "manifest_loaded": integrity.manifest_loaded,
        },
        "run_configuration": None,
        "session": None,
        "synchronization": {
            "state_present": False,
            "executions": 0,
            "conversations": 0,
            "identities": 0,
            "messages": 0,
        },
    }

    if paths.run_configuration.is_file():
        package = ArchivePackage(paths)
        configuration = package.load_run_configuration()
        summary["run_configuration"] = configuration.to_json_dict()

    if paths.session.is_file():
        package = ArchivePackage(paths)
        session = package.load_session()
        summary["session"] = {
            "id": session.id,
            "direction": session.direction.value,
            "paused": session.paused,
            "completed": session.completed,
            "cancelled": session.cancelled,
            "checkpoint": session.checkpoint,
            "error": session.error,
            "started_at": session.started_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }

    repository_path = paths.root / "synchronization.sqlite"
    if repository_path.is_file():
        from archive_sync_engine.repository.execution_log import SQLiteExecutionLog
        from archive_sync_engine.repository.sqlite_state_repository import SQLiteStateRepository

        with SQLiteStateRepository(repository_path) as repository:
            state = repository.load_synchronization_state()
        with SQLiteExecutionLog(repository_path) as execution_log:
            execution_count = execution_log.count()
        summary["synchronization"] = {
            "state_present": True,
            "executions": execution_count,
            "conversations": len(state.conversations),
            "identities": len(state.identities),
            "messages": len(state.messages),
        }

    if args.as_json:
        import json
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        archive = summary["archive"]
        run = summary["run_configuration"]
        session = summary["session"]
        synchronization = summary["synchronization"]
        print(f"Archive: {paths.root}")
        print(f"Integrity: {'VALID' if archive['valid'] else 'INVALID'}")
        print(
            "Canonical records: "
            f"conversations={archive['conversations']} "
            f"identities={archive['identities']} "
            f"messages={archive['messages']} "
            f"attachments={archive['attachments']}"
        )
        print(
            "Run configuration: "
            + (
                f"{run['direction']} input={run['input_adapter']}"
                if run is not None
                else "none"
            )
        )
        if session is None:
            print("Session: none")
        else:
            print(
                "Session: "
                f"{session['id']} direction={session['direction']} "
                f"paused={str(session['paused']).lower()} "
                f"completed={str(session['completed']).lower()} "
                f"cancelled={str(session['cancelled']).lower()}"
            )
            if session["checkpoint"] is not None:
                print(f"Checkpoint: {session['checkpoint']}")
            if session["error"] is not None:
                print(f"Session error: {session['error']}")
        print(
            "Synchronization state: "
            f"present={str(synchronization['state_present']).lower()} "
            f"executions={synchronization['executions']} "
            f"conversations={synchronization['conversations']} "
            f"identities={synchronization['identities']} "
            f"messages={synchronization['messages']}"
        )
        for error in archive["errors"]:
            print(f"ERROR: {error}")

    return 0 if integrity.valid else 1


def _run_preflight(args: argparse.Namespace) -> int:
    """Validate all local prerequisites for a configured run without side effects."""
    setup = load_setup_configuration(args.config)
    archive_path = (
        args.archive.expanduser().resolve()
        if args.archive is not None
        else setup.resolved_archive_path().expanduser().resolve()
    )

    checks: dict[str, object] = {
        "configuration": {
            "valid": True,
            "path": str(setup.source_config_path),
            "discord_guild_ids": list(setup.discord_guild_ids),
            "fluxer_guild_id": setup.fluxer_guild_id,
            "identity_mappings": len(setup.identity_mappings),
            "credentials_resolved": False,
        },
        "archive": {
            "path": str(archive_path),
            "initialized": False,
            "valid": False,
            "errors": [],
        },
    }

    # Resolve every configured secret only to verify availability. Never emit it.
    setup.resolve_discord_token()
    setup.resolve_fluxer_token()
    setup.resolve_identity_mappings()
    checks["configuration"]["credentials_resolved"] = True

    if not archive_path.is_dir():
        checks["archive"]["errors"] = [
            f"Archive Package does not exist: {archive_path}"
        ]
    else:
        checks["archive"]["initialized"] = True
        report = validate_archive_package(ArchivePaths(archive_path))
        checks["archive"]["valid"] = report.valid
        checks["archive"]["errors"] = list(report.errors)

    ready = bool(
        checks["configuration"]["valid"]
        and checks["configuration"]["credentials_resolved"]
        and checks["archive"]["initialized"]
        and checks["archive"]["valid"]
    )
    checks["ready"] = ready

    if args.as_json:
        import json
        print(json.dumps(checks, indent=2, sort_keys=True))
    else:
        configuration = checks["configuration"]
        archive = checks["archive"]
        print(f"Configuration: VALID ({configuration['path']})")
        print(f"Credentials: {'RESOLVED' if configuration['credentials_resolved'] else 'INVALID'}")
        print(f"Identity mappings: {configuration['identity_mappings']}")
        print(f"Archive: {'VALID' if archive['valid'] else 'INVALID'} ({archive['path']})")
        for error in archive["errors"]:
            print(f"ERROR: {error}")
        print(f"Ready: {'YES' if ready else 'NO'}")

    return 0 if ready else 1


def _run_validate(args: argparse.Namespace) -> int:
    report = validate_archive_package(
        ArchivePaths(args.archive),
    )

    if args.as_json:
        import json

        print(
            json.dumps(
                {
                    "valid": report.valid,
                    "errors": list(report.errors),
                    "manifest_loaded": report.manifest_loaded,
                    "conversations_checked": report.conversations_checked,
                    "identities_checked": report.identities_checked,
                    "messages_checked": report.messages_checked,
                    "attachments_checked": report.attachments_checked,
                },
                sort_keys=True,
            )
        )
    else:
        status = "VALID" if report.valid else "INVALID"
        print(status)
        print(f"Conversations checked: {report.conversations_checked}")
        print(f"Identities checked: {report.identities_checked}")
        print(f"Messages checked: {report.messages_checked}")
        print(f"Attachments checked: {report.attachments_checked}")
        for error in report.errors:
            print(f"ERROR: {error}")

    return 0 if report.valid else 1

def _run_init(args: argparse.Namespace) -> int:
    """Create a new empty Archive Package without touching existing data."""
    if args.config is not None:
        setup = load_setup_configuration(args.config)
        archive_path = setup.resolved_archive_path()
        source = str(setup.source_config_path)
    else:
        archive_path = args.archive.expanduser().resolve()
        source = None

    paths = ArchivePaths(archive_path)
    package = ArchivePackage.initialize(paths)

    print(f"Initialized Archive Package: {package.paths.root}")
    if source is not None:
        print(f"Configuration: {source}")
    return 0


def _run_import(args: argparse.Namespace) -> int:
    """Import one registered source adapter into an Archive Package."""
    setup = load_setup_configuration(args.config)
    archive_path = (
        args.archive.expanduser().resolve()
        if args.archive is not None
        else setup.resolved_archive_path()
    )
    paths = ArchivePaths(archive_path)
    if not paths.database.is_file() or not paths.manifest.is_file():
        raise ConfigurationError(
            f"Archive Package is not initialized: {paths.root}. "
            "Run 'archive-sync-engine init --archive <path>' first."
        )
    report = validate_archive_package(paths)
    if not report.valid:
        raise ConfigurationError(
            f"Archive Package is invalid: {'; '.join(report.errors)}"
        )

    adapter_name = args.input_adapter.strip().lower()
    try:
        descriptor = default_adapter_registry().require_source(adapter_name)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc

    if args.input_scope:
        scope = tuple(value.strip() for value in args.input_scope)
        if any(not value for value in scope):
            raise ConfigurationError("Input scope values must not be empty.")
    elif adapter_name == "discord":
        scope = tuple(str(value) for value in setup.discord_guild_ids)
    else:
        raise ConfigurationError(
            f"Input scope must be provided for source adapter {descriptor.name!r}."
        )

    if adapter_name != "discord":
        raise ConfigurationError(
            f"No concrete source runtime configuration is currently available "
            f"for adapter {adapter_name!r}."
        )

    credentials = setup.resolve_credentials()
    discord_config = DiscordClientConfig(
        token=credentials.discord_token,
        guild_ids=tuple(int(value) for value in scope),
    )
    runtime_request = SourceRuntimeRequest(
        adapter=adapter_name,
        scope=scope,
        archive_path=paths.root,
        adapter_config={
            "discord": discord_config,
        },
    )

    if not args.resume:
        ArchivePackage(paths).save_run_configuration(
            SyncRunConfiguration(
                direction=RunDirection.IMPORT,
                input_adapter=adapter_name,
                input_scope=scope,
            )
        )
    else:
        try:
            run_configuration = ArchivePackage(paths).load_run_configuration()
        except FileNotFoundError as exc:
            raise ConfigurationError(
                f"No persisted run configuration exists in Archive Package: {paths.root}."
            ) from exc
        if run_configuration.direction is not RunDirection.IMPORT:
            raise ConfigurationError(
                "The persisted run configuration is not an import run."
            )
        if (run_configuration.input_adapter != adapter_name or
                run_configuration.input_scope != scope):
            raise ConfigurationError(
                "Import resume arguments do not match the persisted adapter or scope."
            )
        try:
            ArchivePackage(paths).load_import_state()
        except FileNotFoundError as exc:
            raise ConfigurationError(
                f"No importer checkpoint exists in Archive Package: {paths.root}."
            ) from exc

    runtime = default_source_runtime_registry().create(
        adapter_name,
        runtime_request,
    )
    with runtime:
        runtime.import_to_archive(paths, resume=args.resume)

    return 0


def _run_export(args: argparse.Namespace) -> int:
    """Export an existing Archive through a registered destination runtime."""
    setup = load_setup_configuration(args.config)
    archive_path = (
        args.archive.expanduser().resolve()
        if args.archive is not None
        else setup.resolved_archive_path()
    )
    paths = ArchivePaths(archive_path)
    if not paths.database.is_file() or not paths.manifest.is_file():
        raise ConfigurationError(
            f"Archive Package is not initialized: {paths.root}. "
            "Run 'archive-sync-engine init --archive <path>' first."
        )
    report = validate_archive_package(paths)
    if not report.valid:
        raise ConfigurationError(
            f"Archive Package is invalid: {'; '.join(report.errors)}"
        )

    destination_adapter = args.destination_adapter.strip().lower()
    try:
        default_adapter_registry().require_destination(destination_adapter)
        destination_registry = default_destination_runtime_registry()
        destination_scope = (
            tuple(value.strip() for value in args.destination_scope)
            if args.destination_scope
            else ((setup.fluxer_guild_id,) if destination_adapter == "fluxer" else ())
        )
        if not destination_scope:
            raise ConfigurationError(
                f"Destination scope must be provided for destination adapter "
                f"{destination_adapter!r}."
            )
        if any(not value for value in destination_scope):
            raise ConfigurationError("Destination scope values must not be empty.")

        if destination_adapter != "fluxer":
            raise ConfigurationError(
                f"No concrete destination runtime configuration is currently "
                f"available for adapter {destination_adapter!r}."
            )

        credentials = setup.resolve_credentials()
        runtime_request = DestinationRuntimeRequest(
            adapter=destination_adapter,
            scope=destination_scope,
            archive_path=paths.root,
            adapter_config={
                "fluxer": FluxerClientConfig(
                    token=credentials.fluxer_token,
                    is_bot=True,
                    api_url=args.fluxer_api_url,
                    max_retries=args.fluxer_max_retries,
                ),
                "identity_mappings": credentials.identity_mappings,
            },
        )
        runtime = destination_registry.create(destination_adapter, runtime_request)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc

    with Archive(paths) as archive, runtime:
        CanonicalExporter().export(
            archive=archive,
            destination=runtime.adapter,
            asset_store=archive.asset_store,
        )

    return 0


def _run_resume(args: argparse.Namespace) -> int:
    """Resume the persisted run using current human-authored credentials.

    Persisted run configuration supplies the source/destination adapters and
    scopes. Secrets are deliberately read again from config.yaml and are never
    recovered from run.json.
    """
    setup = load_setup_configuration(args.config)
    configured_archive = setup.resolved_archive_path()
    archive_path = args.archive.expanduser().resolve() if args.archive is not None else configured_archive
    paths = ArchivePaths(archive_path)

    package = ArchivePackage(paths)
    try:
        run_configuration = package.load_run_configuration()
    except FileNotFoundError as exc:
        raise ConfigurationError(
            f"No persisted run configuration exists in Archive Package: {paths.root}. "
            "Run an import or sync first."
        ) from exc

    try:
        session = package.load_session()
    except FileNotFoundError as exc:
        raise ConfigurationError(
            f"No persisted run session exists in Archive Package: {paths.root}."
        ) from exc

    if session.completed:
        raise ConfigurationError("The persisted run is already completed; it cannot be resumed.")
    if session.cancelled:
        raise ConfigurationError("The persisted run was cancelled and cannot be resumed.")
    if run_configuration.direction is RunDirection.IMPORT:
        if args.archive is not None:
            archive_path = args.archive.expanduser().resolve()
        try:
            package.load_import_state()
        except FileNotFoundError as exc:
            raise ConfigurationError(
                f"No importer checkpoint exists in Archive Package: {paths.root}."
            ) from exc
        if run_configuration.input_adapter != "discord":
            raise ConfigurationError(
                f"No concrete source runtime is currently available for "
                f"adapter {run_configuration.input_adapter!r}."
            )
        try:
            scope = tuple(str(value) for value in run_configuration.input_scope)
            discord_config = DiscordClientConfig(
                token=setup.resolve_discord_token(),
                guild_ids=tuple(int(value) for value in scope),
            )
        except ValueError as exc:
            raise ConfigurationError(
                "The persisted Discord input scope contains a non-numeric guild ID."
            ) from exc
        request = SourceRuntimeRequest(
            adapter=run_configuration.input_adapter,
            scope=scope,
            archive_path=paths.root,
            adapter_config={"discord": discord_config},
        )
        runtime = default_source_runtime_registry().create(
            run_configuration.input_adapter,
            request,
        )
        with runtime:
            runtime.import_to_archive(paths, resume=True)
        return 0

    if run_configuration.direction is not RunDirection.SYNC:
        raise ConfigurationError(
            f"Unsupported persisted run direction: {run_configuration.direction.value!r}."
        )
    if run_configuration.destination_adapter is None:
        raise ConfigurationError(
            "The persisted sync run has no destination adapter."
        )
    _require_supported_sync_pair(
        run_configuration.input_adapter,
        run_configuration.destination_adapter,
    )
    if not run_configuration.input_scope or not run_configuration.destination_scope:
        raise ConfigurationError("The persisted run configuration has no source/destination scope.")

    try:
        discord_guild_ids = tuple(int(value) for value in run_configuration.input_scope)
    except ValueError as exc:
        raise ConfigurationError(
            "The persisted Discord input scope contains a non-numeric guild ID."
        ) from exc

    resume_args = argparse.Namespace(
        config=args.config,
        discord_token=None,
        discord_guild_id=list(discord_guild_ids),
        fluxer_token=None,
        fluxer_guild_id=run_configuration.destination_scope[0],
        archive=archive_path,
        fluxer_api_url=None,
        fluxer_max_retries=4,
        resume=True,
        dry_run=False,
        fluxer_identity=[],
    )
    return _run_sync(resume_args)


def _run_sync(args: argparse.Namespace) -> int:
    setup = load_setup_configuration(args.config) if args.config is not None else None

    if args.dry_run and args.resume:
        raise ConfigurationError("--dry-run cannot be combined with --resume.")

    discord_token = (
        args.discord_token
        if args.discord_token is not None
        else (setup.resolve_discord_token() if setup is not None else None)
    )
    if not discord_token:
        raise ConfigurationError(
            "Discord authentication token is required; provide --discord-token "
            "or configure discord.token/token_file in --config."
        )

    discord_guild_ids = tuple(args.discord_guild_id or ())
    if not discord_guild_ids and setup is not None:
        discord_guild_ids = setup.discord_guild_ids
    if not discord_guild_ids:
        raise ConfigurationError(
            "At least one Discord guild ID is required; provide "
            "--discord-guild-id or configure discord.guild_id in --config."
        )

    fluxer_token = (
        args.fluxer_token
        if args.fluxer_token is not None
        else (setup.resolve_fluxer_token() if setup is not None else None)
    )
    if not fluxer_token:
        raise ConfigurationError(
            "Fluxer authentication token is required; provide --fluxer-token "
            "or configure fluxer.token/token_file in --config."
        )

    fluxer_guild_id = (
        args.fluxer_guild_id
        if args.fluxer_guild_id is not None
        else (setup.fluxer_guild_id if setup is not None else None)
    )
    if not fluxer_guild_id:
        raise ConfigurationError(
            "Fluxer server ID is required; provide --fluxer-guild-id or configure "
            "fluxer.server_id in --config."
        )

    archive_path = (
        args.archive
        if args.archive is not None
        else (setup.resolved_archive_path() if setup is not None else None)
    )
    if archive_path is None:
        raise ConfigurationError(
            "Archive path is required; provide --archive or configure archive.path "
            "in --config."
        )

    identity_mappings = (
        _parse_identity_mappings(args.fluxer_identity)
        if args.fluxer_identity
        else (setup.resolve_identity_mappings() if setup is not None else ())
    )

    input_adapter = "discord"
    destination_adapter = "fluxer"
    _require_supported_sync_pair(input_adapter, destination_adapter)

    paths = ArchivePaths(archive_path.expanduser().resolve())
    if not paths.database.is_file() or not paths.manifest.is_file():
        raise ConfigurationError(
            f"Archive Package is not initialized: {paths.root}. "
            "Run 'archive-sync-engine init --archive <path>' first."
        )
    report = validate_archive_package(paths)
    if not report.valid:
        raise ConfigurationError(
            f"Archive Package is invalid: {'; '.join(report.errors)}"
        )

    config = DiscordFluxerSyncConfig(
        discord=DiscordClientConfig(
            token=discord_token,
            guild_ids=discord_guild_ids,
        ),
        fluxer=FluxerClientConfig(
            token=fluxer_token,
            is_bot=True,
            api_url=args.fluxer_api_url,
            max_retries=args.fluxer_max_retries,
        ),
        fluxer_guild_id=fluxer_guild_id,
        archive_paths=paths,
        identity_mappings=identity_mappings,
    )

    if not args.dry_run:
        ArchivePackage(paths).save_run_configuration(
            SyncRunConfiguration(
                direction=RunDirection.SYNC,
                input_adapter="discord",
                input_scope=tuple(str(value) for value in discord_guild_ids),
                destination_adapter="fluxer",
                destination_scope=(str(fluxer_guild_id),),
            )
        )

    def build_discord_fluxer_runtime(request: SyncRuntimeRequest) -> DiscordFluxerSyncRuntime:
        if request.input_adapter != "discord" or request.destination_adapter != "fluxer":
            raise ConfigurationError("The current Discord/Fluxer runtime cannot handle this adapter pair.")
        if len(request.destination_scope) != 1:
            raise ConfigurationError("Fluxer destination scope must contain exactly one server ID.")
        try:
            discord_config = request.adapter_config["discord"]
            fluxer_config = request.adapter_config["fluxer"]
        except KeyError as exc:
            raise ConfigurationError(f"Missing runtime configuration for adapter {exc.args[0]!r}.") from exc
        runtime_config = DiscordFluxerSyncConfig(
            discord=discord_config,
            fluxer=fluxer_config,
            fluxer_guild_id=request.destination_scope[0],
            archive_paths=ArchivePaths(request.archive_path),
            identity_mappings=tuple(request.adapter_config.get("identity_mappings", ())),
        )
        return DiscordFluxerSyncRuntime(runtime_config)

    runtime_registry = default_sync_runtime_registry(build_discord_fluxer_runtime)
    runtime_request = SyncRuntimeRequest(
        input_adapter=input_adapter,
        input_scope=tuple(str(value) for value in discord_guild_ids),
        destination_adapter=destination_adapter,
        destination_scope=(str(fluxer_guild_id),),
        archive_path=paths.root,
        adapter_config={
            "discord": config.discord,
            "fluxer": config.fluxer,
            "identity_mappings": identity_mappings,
        },
    )
    runtime = runtime_registry.create(input_adapter, destination_adapter, runtime_request)
    with runtime:
        if args.dry_run:
            operations = runtime.dry_run()
            print(f"Dry run: {len(operations)} synchronization operations planned.")
        else:
            runtime.run(resume_import=args.resume)

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    secrets = [
        value
        for name in ("discord_token", "fluxer_token")
        for value in (getattr(args, name, None),)
        if isinstance(value, str) and value
    ]
    logger = configure_logging(
        level=getattr(args, "log_level", "WARNING"),
        log_file=getattr(args, "log_file", None),
        secrets=secrets,
    )
    logger.info("Starting command: %s", args.command)

    try:
        if args.command == "init":
            return _run_init(args)
        if args.command == "import":
            return _run_import(args)
        if args.command == "preflight":
            return _run_preflight(args)
        if args.command == "validate":
            return _run_validate(args)
        if args.command == "export":
            return _run_export(args)
        if args.command == "resume":
            return _run_resume(args)
        if args.command == "sync":
            return _run_sync(args)
        if args.command == "adapters":
            return _run_adapters(args)
        if args.command == "diagnostics":
            return _run_diagnostics(args)
    except (ValueError, ConfigurationError) as exc:
        report_expected_error(exc)
        parser.error(str(exc))
    except Exception as exc:
        report_unexpected_error(exc)
        parser.error("Unexpected application error; consult the log for details.")

    parser.error("No command was selected.")
    return 2
