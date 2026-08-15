"""Application-level configuration and credential resolution for the CLI."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 is unsupported.
    tomllib = None  # type: ignore[assignment]


class CliConfigurationError(ValueError):
    """Raised when CLI configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class SyncCliConfig:
    """Resolved application configuration for a Discord-to-Fluxer sync."""

    discord_token: str
    discord_guild_ids: tuple[int, ...]
    fluxer_token: str
    fluxer_guild_id: str
    archive: Path
    state_db: Path | None = None
    fluxer_api_url: str | None = None
    fluxer_max_retries: int = 4
    fluxer_identity: tuple[str, ...] = ()
    resume: bool = False


@dataclass(frozen=True, slots=True)
class _ConfigFile:
    """Non-secret configuration loaded from an optional TOML file."""

    discord_guild_ids: tuple[int, ...] = ()
    fluxer_guild_id: str | None = None
    archive: Path | None = None
    state_db: Path | None = None
    fluxer_api_url: str | None = None
    fluxer_max_retries: int | None = None
    fluxer_identity: tuple[str, ...] = ()


def _require_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CliConfigurationError(f"Configuration value '{name}' must be a non-empty string.")
    return value.strip()


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, name)


def _parse_guild_ids(value: object, name: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise CliConfigurationError(f"Configuration value '{name}' must be a non-empty array.")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise CliConfigurationError(
                f"Configuration value '{name}' must contain positive integers."
            )
        result.append(item)
    return tuple(result)


def _parse_identity_values(value: object, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise CliConfigurationError(
            f"Configuration value '{name}' must be an array of non-empty strings."
        )
    return tuple(value)


def _load_config_file(path: Path) -> _ConfigFile:
    if tomllib is None:  # pragma: no cover
        raise CliConfigurationError("TOML configuration requires Python 3.11 or newer.")
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise CliConfigurationError(f"Configuration file does not exist: {path}") from exc
    except OSError as exc:
        raise CliConfigurationError(f"Unable to read configuration file '{path}': {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CliConfigurationError(f"Invalid TOML configuration '{path}': {exc}") from exc

    section = document.get("sync", document)
    if not isinstance(section, dict):
        raise CliConfigurationError("Configuration must contain a [sync] table.")

    guild_ids = section.get("discord_guild_ids", ())
    if guild_ids:
        discord_guild_ids = _parse_guild_ids(guild_ids, "discord_guild_ids")
    else:
        discord_guild_ids = ()

    retries = section.get("fluxer_max_retries")
    if retries is not None and (isinstance(retries, bool) or not isinstance(retries, int) or retries < 0):
        raise CliConfigurationError("Configuration value 'fluxer_max_retries' must be a non-negative integer.")

    return _ConfigFile(
        discord_guild_ids=discord_guild_ids,
        fluxer_guild_id=_optional_string(section.get("fluxer_guild_id"), "fluxer_guild_id"),
        archive=Path(_require_string(section["archive"], "archive")) if "archive" in section else None,
        state_db=Path(_require_string(section["state_db"], "state_db")) if "state_db" in section else None,
        fluxer_api_url=_optional_string(section.get("fluxer_api_url"), "fluxer_api_url"),
        fluxer_max_retries=retries,
        fluxer_identity=_parse_identity_values(section.get("fluxer_identity"), "fluxer_identity"),
    )


def _first_nonempty(*values: str | None) -> str | None:
    for value in values:
        if value is not None and value.strip():
            return value.strip()
    return None


def resolve_sync_config(
    *,
    command_values: Mapping[str, object],
    environment: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> SyncCliConfig:
    """Resolve sync configuration with CLI > environment > TOML precedence.

    Credentials intentionally come only from command-line arguments or
    environment variables. They are not read from the TOML configuration.
    """

    env = environment if environment is not None else os.environ
    file_config = _load_config_file(config_path) if config_path is not None else _ConfigFile()

    def value(name: str, env_name: str, file_value: object = None) -> object:
        command_value = command_values.get(name)
        if command_value is not None:
            return command_value
        env_value = env.get(env_name)
        if env_value is not None and env_value.strip():
            return env_value.strip()
        return file_value

    discord_token = _first_nonempty(
        command_values.get("discord_token") if isinstance(command_values.get("discord_token"), str) else None,
        env.get("ARCHIVE_SYNC_DISCORD_TOKEN"),
    )
    if discord_token is None:
        raise CliConfigurationError(
            "Discord token is required; provide --discord-token or ARCHIVE_SYNC_DISCORD_TOKEN."
        )

    fluxer_token = _first_nonempty(
        command_values.get("fluxer_token") if isinstance(command_values.get("fluxer_token"), str) else None,
        env.get("ARCHIVE_SYNC_FLUXER_TOKEN"),
    )
    if fluxer_token is None:
        raise CliConfigurationError(
            "Fluxer token is required; provide --fluxer-token or ARCHIVE_SYNC_FLUXER_TOKEN."
        )

    guild_values = command_values.get("discord_guild_id")
    if guild_values is not None:
        guild_ids = tuple(int(item) for item in guild_values)  # argparse supplies integers.
    else:
        guild_ids = file_config.discord_guild_ids
    if not guild_ids:
        raise CliConfigurationError(
            "At least one Discord guild ID is required; provide --discord-guild-id or config.discord_guild_ids."
        )
    if any(item <= 0 for item in guild_ids):
        raise CliConfigurationError("Discord guild IDs must be positive integers.")

    fluxer_guild_id = value("fluxer_guild_id", "ARCHIVE_SYNC_FLUXER_GUILD_ID", file_config.fluxer_guild_id)
    if not isinstance(fluxer_guild_id, str) or not fluxer_guild_id.strip():
        raise CliConfigurationError(
            "Fluxer guild ID is required; provide --fluxer-guild-id, ARCHIVE_SYNC_FLUXER_GUILD_ID, or config.fluxer_guild_id."
        )

    archive_value = value("archive", "ARCHIVE_SYNC_ARCHIVE", file_config.archive)
    if archive_value is None:
        raise CliConfigurationError(
            "Archive path is required; provide --archive, ARCHIVE_SYNC_ARCHIVE, or config.archive."
        )
    archive = Path(archive_value)

    state_db_value = value("state_db", "ARCHIVE_SYNC_STATE_DB", file_config.state_db)
    state_db = Path(state_db_value) if state_db_value is not None else None

    api_url = value("fluxer_api_url", "ARCHIVE_SYNC_FLUXER_API_URL", file_config.fluxer_api_url)
    if api_url is not None and not isinstance(api_url, str):
        raise CliConfigurationError("Fluxer API URL must be a string.")

    retries = value("fluxer_max_retries", "ARCHIVE_SYNC_FLUXER_MAX_RETRIES", file_config.fluxer_max_retries)
    if retries is None:
        retries = 4
    try:
        retries = int(retries)
    except (TypeError, ValueError) as exc:
        raise CliConfigurationError("Fluxer max retries must be a non-negative integer.") from exc
    if retries < 0:
        raise CliConfigurationError("Fluxer max retries must be a non-negative integer.")

    identities = command_values.get("fluxer_identity")
    if identities is None:
        identities = file_config.fluxer_identity
    if isinstance(identities, str):
        identities = (identities,)
    identity_values = tuple(identities or ())

    return SyncCliConfig(
        discord_token=discord_token,
        discord_guild_ids=guild_ids,
        fluxer_token=fluxer_token,
        fluxer_guild_id=fluxer_guild_id.strip(),
        archive=archive,
        state_db=state_db,
        fluxer_api_url=api_url,
        fluxer_max_retries=retries,
        fluxer_identity=identity_values,
        resume=bool(command_values.get("resume", False)),
    )
