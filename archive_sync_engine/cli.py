"""Command-line entry point for Archive-Sync Engine."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from archive_sync_engine.adapters.discord.runtime import DiscordClientConfig
from archive_sync_engine.adapters.fluxer import FluxerIdentityMapping
from archive_sync_engine.adapters.fluxer_runtime import FluxerClientConfig
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.archive.package import ArchivePackage
from archive_sync_engine.config import ConfigurationError, load_setup_configuration
from archive_sync_engine.archive import validate_archive_package
from archive_sync_engine.repository.sqlite_state_repository import SQLiteStateRepository
from archive_sync_engine.sync.run_configuration import RunDirection, SyncRunConfiguration
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
        "--fluxer-identity",
        action="append",
        default=[],
        metavar="USERNAME[:AUTH_TOKEN]",
        help=(
            "Map a canonical identity to a Fluxer actor. Repeat as needed. "
            "Omit AUTH_TOKEN to use the bot account for that identity."
        ),
    )


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
    return parser


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


def _run_diagnostics(args: argparse.Namespace) -> int:
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

def _run_sync(args: argparse.Namespace) -> int:
    setup = load_setup_configuration(args.config) if args.config is not None else None

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

    ArchivePackage(paths).save_run_configuration(
        SyncRunConfiguration(
            direction=RunDirection.SYNC,
            input_adapter="discord",
            input_scope=tuple(str(value) for value in discord_guild_ids),
            destination_adapter="fluxer",
            destination_scope=(str(fluxer_guild_id),),
        )
    )

    with DiscordFluxerSyncRuntime(config) as runtime:
        runtime.run(resume_import=args.resume)

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            return _run_validate(args)
        if args.command == "sync":
            return _run_sync(args)
        if args.command == "diagnostics":
            return _run_diagnostics(args)
    except (ValueError, ConfigurationError) as exc:
        parser.error(str(exc))

    parser.error("No command was selected.")
    return 2
