"""Human-authored application configuration for Archive-Sync Engine.

This module defines the setup configuration used before an Archive exists or
while selecting resources for an existing Archive. It deliberately remains at
the application boundary: canonical Archive identities and synchronization
state are not serialized into this configuration format.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping
import re

import yaml

from archive_sync_engine.adapters.fluxer import FluxerIdentityMapping


class ConfigurationError(ValueError):
    """Raised when an application configuration file is invalid."""


@dataclass(frozen=True, slots=True)
class SecretSource:
    """A secret supplied inline or through a file, but never both."""

    value: str | None = None
    file: Path | None = None

    def resolve(self, *, base_dir: Path, label: str) -> str:
        if (self.value is None) == (self.file is None):
            raise ConfigurationError(
                f"{label} must define exactly one of the configured secret "
                "values."
            )

        if self.value is not None:
            if not self.value:
                raise ConfigurationError(f"{label} must not be empty.")
            return self.value

        assert self.file is not None
        path = self.file if self.file.is_absolute() else base_dir / self.file
        try:
            secret = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigurationError(
                f"Unable to read {label} file {str(path)!r}: {exc}"
            ) from exc
        if not secret:
            raise ConfigurationError(f"{label} file {str(path)!r} is empty.")
        return secret


@dataclass(frozen=True, slots=True)
class SetupUserMapping:
    """A human-authored stable external identity mapping.

    ``platform`` identifies which adapter's stable user ID is being
    configured. Discord mappings may additionally carry a per-user Discord
    authentication secret. Fluxer mappings identify a stable Fluxer user and
    retain the credentials used when that identity is represented on Fluxer.
    """

    platform: Literal["discord", "fluxer"]
    external_user_id: str
    fluxer_username: str
    fluxer_auth: SecretSource
    discord_auth: SecretSource | None = None

    @property
    def discord_user_id(self) -> str:
        """Return the stable Discord user ID for a Discord mapping."""
        if self.platform != "discord":
            raise AttributeError("This mapping is not a Discord mapping.")
        return self.external_user_id

    @property
    def fluxer_user_id(self) -> str:
        """Return the stable Fluxer user ID for a Fluxer mapping."""
        if self.platform != "fluxer":
            raise AttributeError("This mapping is not a Fluxer mapping.")
        return self.external_user_id

    @property
    def canonical_identity_key(self) -> str:
        """Return the canonical key produced by the source adapter."""
        return f"{self.platform}:user:{self.external_user_id}"

    def resolve(self, *, base_dir: Path) -> FluxerIdentityMapping:
        if self.platform != "discord":
            raise ConfigurationError(
                "Only Discord source user mappings can currently be resolved "
                "into Fluxer destination identity mappings."
            )
        return FluxerIdentityMapping(
            username=self.canonical_identity_key,
            fluxer_auth_key=self.fluxer_auth.resolve(
                base_dir=base_dir,
                label=f"Fluxer auth for Discord user {self.external_user_id}",
            ),
            fluxer_username=self.fluxer_username,
        )

    def resolve_discord_auth(self, *, base_dir: Path) -> str:
        """Resolve this mapping's optional per-user Discord authentication."""
        if self.platform != "discord":
            raise ConfigurationError(
                "Per-user Discord authentication is only valid for Discord mappings."
            )
        if self.discord_auth is None:
            raise ConfigurationError(
                f"No per-user Discord authentication is configured for user "
                f"{self.external_user_id}."
            )
        return self.discord_auth.resolve(
            base_dir=base_dir,
            label=f"Discord auth for user {self.external_user_id}",
        )


@dataclass(frozen=True, slots=True)
class ResolvedSetupCredentials:
    """Resolved secrets from one validated setup configuration.

    Resolution is performed once at the application boundary so missing or
    unreadable secret files fail before runtime clients are constructed.
    Stable per-user mappings remain keyed by their external platform IDs.
    """

    discord_token: str | None
    fluxer_token: str
    discord_user_auth: Mapping[str, str]
    fluxer_user_auth: Mapping[str, str]
    identity_mappings: tuple[FluxerIdentityMapping, ...]


@dataclass(frozen=True, slots=True)
class SetupConfiguration:
    """Validated human-authored setup configuration."""

    source_config_path: Path
    archive_path: Path
    input_adapter: str
    input_scope: tuple[str, ...]
    discord_token: SecretSource | None
    discord_guild_ids: tuple[int, ...]
    fluxer_token: SecretSource | None
    fluxer_guild_id: str | None
    identity_mappings: tuple[SetupUserMapping, ...] = ()
    fluxer_user_mappings: tuple[SetupUserMapping, ...] = ()
    between_messages_seconds: float = 0.0
    between_channels_seconds: float = 0.0

    @property
    def config_directory(self) -> Path:
        return self.source_config_path.parent

    def resolved_archive_path(self) -> Path:
        return _resolve_path(self.archive_path, self.config_directory)

    def resolve_credentials(
        self,
        *,
        require_discord: bool = True,
        require_fluxer: bool = True,
    ) -> ResolvedSetupCredentials:
        """Resolve every configured authentication secret exactly once.

        This is the application boundary for turning human-authored secret
        sources into runtime credentials. File-backed secrets are resolved
        relative to the configuration file, while inline secrets are returned
        unchanged.
        """
        base_dir = self.config_directory
        if not require_discord and not require_fluxer:
            raise ConfigurationError(
                "At least one adapter credential set must be requested."
            )

        discord_token: str | None = None
        fluxer_token = ""
        discord_user_auth: dict[str, str] = {}
        fluxer_user_auth: dict[str, str] = {}
        identity_mappings: tuple[FluxerIdentityMapping, ...] = ()

        if require_discord:
            if self.discord_token is None:
                raise ConfigurationError("Discord configuration is required for this workflow.")
            discord_token = self.discord_token.resolve(
                base_dir=base_dir,
                label="Discord token",
            )
            discord_user_auth = {
                mapping.discord_user_id: mapping.resolve_discord_auth(base_dir=base_dir)
                for mapping in self.identity_mappings
                if mapping.discord_auth is not None
            }

        if require_fluxer:
            if self.fluxer_token is None:
                raise ConfigurationError("Fluxer configuration is required for this workflow.")
            fluxer_token = self.fluxer_token.resolve(
                base_dir=base_dir,
                label="Fluxer token",
            )
            fluxer_user_auth = {
                mapping.fluxer_user_id: mapping.fluxer_auth.resolve(
                    base_dir=base_dir,
                    label=f"Fluxer auth for Fluxer user {mapping.fluxer_user_id}",
                )
                for mapping in self.fluxer_user_mappings
            }
            identity_mappings = tuple(
                mapping.resolve(base_dir=base_dir)
                for mapping in self.identity_mappings
            )

        return ResolvedSetupCredentials(
            discord_token=discord_token,
            fluxer_token=fluxer_token,
            discord_user_auth=discord_user_auth,
            fluxer_user_auth=fluxer_user_auth,
            identity_mappings=identity_mappings,
        )

    def resolve_discord_token(self) -> str:
        return self.resolve_credentials().discord_token

    def resolve_fluxer_token(self) -> str:
        return self.resolve_credentials().fluxer_token

    def resolve_identity_mappings(self) -> tuple[FluxerIdentityMapping, ...]:
        return self.resolve_credentials().identity_mappings

    def resolve_discord_user_auth(self) -> dict[str, str]:
        """Resolve configured per-user Discord credentials by stable user ID."""
        return dict(self.resolve_credentials().discord_user_auth)

    def resolve_fluxer_user_auth(self) -> dict[str, str]:
        """Resolve configured per-user Fluxer credentials by stable user ID."""
        return dict(self.resolve_credentials().fluxer_user_auth)


def load_setup_configuration(
    path: str | Path,
    *,
    require_discord: bool = True,
    require_fluxer: bool = True,
) -> SetupConfiguration:
    """Load configuration, requiring only the adapter credentials a workflow needs."""
    config_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(
            f"Unable to read configuration file {str(config_path)!r}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            f"Unable to parse YAML configuration {str(config_path)!r}: {exc}"
        ) from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ConfigurationError("The configuration root must be a YAML mapping.")

    archive = _mapping(raw, "archive")
    discord = _mapping(raw, "discord", required=require_discord)
    fluxer = _mapping(raw, "fluxer", required=require_fluxer)
    delays = _mapping(raw, "delays", required=False)
    input_config = _mapping(raw, "input", required=False)
    mappings = _mapping(raw, "user_mappings", required=False)

    archive_path = _required_string(archive, "path", "archive.path")

    input_adapter_value = input_config.get("adapter")
    if input_adapter_value is None:
        input_adapter = "discord"
    else:
        input_adapter = _required_identifier(
            input_config, "adapter", "input.adapter"
        ).lower()

    input_scope_value = input_config.get("scope")
    if input_scope_value is None:
        input_scope = tuple(str(value) for value in (
            _guild_ids(discord.get("guild_id") if discord.get("guild_id") is not None else discord.get("guild_ids"), "discord.guild_id")
            if require_discord and input_adapter == "discord" else ()
        ))
    else:
        if not isinstance(input_scope_value, (list, tuple)):
            raise ConfigurationError("input.scope must be a YAML sequence.")
        input_scope = tuple(str(value).strip() for value in input_scope_value)
        if any(not value for value in input_scope):
            raise ConfigurationError("input.scope values must not be empty.")
    discord_token = (
        _secret_source(discord, "token", "token_file", "discord")
        if require_discord else None
    )
    fluxer_token = (
        _secret_source(fluxer, "token", "token_file", "fluxer")
        if require_fluxer else None
    )

    discord_guild_value = discord.get("guild_id")
    if discord_guild_value is None:
        discord_guild_value = discord.get("guild_ids")
    discord_guild_ids = (
        _guild_ids(discord_guild_value, "discord.guild_id")
        if require_discord else ()
    )

    fluxer_guild_id = (
        _required_identifier(fluxer, "server_id", "fluxer.server_id")
        if require_fluxer else None
    )

    identity_mappings, fluxer_user_mappings = _parse_user_mappings(mappings)

    between_messages = _nonnegative_float(
        delays.get("between_messages_seconds", 0.0),
        "delays.between_messages_seconds",
    )
    between_channels = _nonnegative_float(
        delays.get("between_channels_seconds", 0.0),
        "delays.between_channels_seconds",
    )

    return SetupConfiguration(
        source_config_path=config_path,
        archive_path=Path(archive_path).expanduser(),
        input_adapter=input_adapter,
        input_scope=input_scope,
        discord_token=discord_token,
        discord_guild_ids=discord_guild_ids,
        fluxer_token=fluxer_token,
        fluxer_guild_id=fluxer_guild_id,
        identity_mappings=identity_mappings,
        fluxer_user_mappings=fluxer_user_mappings,
        between_messages_seconds=between_messages,
        between_channels_seconds=between_channels,
    )


def _parse_user_mappings(
    value: Mapping[str, Any],
) -> tuple[tuple[SetupUserMapping, ...], tuple[SetupUserMapping, ...]]:
    if not value:
        return (), ()

    discord_entries = value.get("discord")
    fluxer_entries = value.get("fluxer")
    if discord_entries is not None and not isinstance(discord_entries, Mapping):
        raise ConfigurationError("user_mappings.discord must be a YAML mapping.")
    if fluxer_entries is not None and not isinstance(fluxer_entries, Mapping):
        raise ConfigurationError("user_mappings.fluxer must be a YAML mapping.")

    discord_mappings: list[SetupUserMapping] = []
    for external_id, raw_mapping in (discord_entries or {}).items():
        user_id = _stable_user_id(
            external_id,
            f"user_mappings.discord",
            platform="Discord",
        )
        if not isinstance(raw_mapping, Mapping):
            raise ConfigurationError(
                f"user_mappings.discord.{user_id} must be a YAML mapping."
            )

        fluxer_username = _required_fluxer_username(
            raw_mapping,
            f"user_mappings.discord.{user_id}.fluxer_username",
        )
        fluxer_auth = _secret_source(
            raw_mapping,
            "fluxer_auth_key",
            "fluxer_auth_key_file",
            f"user_mappings.discord.{user_id}",
        )
        discord_auth = _optional_secret_source(
            raw_mapping,
            "discord_auth_key",
            "discord_auth_key_file",
            f"user_mappings.discord.{user_id}",
        )
        discord_mappings.append(
            SetupUserMapping(
                platform="discord",
                external_user_id=user_id,
                fluxer_username=fluxer_username,
                fluxer_auth=fluxer_auth,
                discord_auth=discord_auth,
            )
        )

    fluxer_mappings: list[SetupUserMapping] = []
    for external_id, raw_mapping in (fluxer_entries or {}).items():
        user_id = _stable_user_id(
            external_id,
            "user_mappings.fluxer",
            platform="Fluxer",
        )
        if not isinstance(raw_mapping, Mapping):
            raise ConfigurationError(
                f"user_mappings.fluxer.{user_id} must be a YAML mapping."
            )

        fluxer_username = _required_fluxer_username(
            raw_mapping,
            f"user_mappings.fluxer.{user_id}.fluxer_username",
        )
        fluxer_auth = _secret_source(
            raw_mapping,
            "fluxer_auth_key",
            "fluxer_auth_key_file",
            f"user_mappings.fluxer.{user_id}",
        )
        fluxer_mappings.append(
            SetupUserMapping(
                platform="fluxer",
                external_user_id=user_id,
                fluxer_username=fluxer_username,
                fluxer_auth=fluxer_auth,
            )
        )

    return tuple(discord_mappings), tuple(fluxer_mappings)


def _stable_user_id(value: Any, label: str, *, platform: str) -> str:
    user_id = str(value).strip()
    if not user_id:
        raise ConfigurationError(f"{label} mapping IDs must not be empty.")
    if not user_id.isdigit():
        raise ConfigurationError(
            f"{platform} user mapping IDs must use stable numeric {platform} user IDs. "
            f"Received {user_id!r}."
        )
    return user_id


def _required_fluxer_username(
    mapping: Mapping[str, Any],
    label: str,
) -> str:
    value = _required_string(mapping, "fluxer_username", label)
    if re.fullmatch(r".+#[0-9]{4}", value) is None:
        raise ConfigurationError(
            f"{label} must include a '#' followed by exactly four digits "
            "(for example, 'BobsFluxerAccount#0909')."
        )
    return value


def _optional_secret_source(
    mapping: Mapping[str, Any],
    value_key: str,
    file_key: str,
    label: str,
) -> SecretSource | None:
    value = mapping.get(value_key)
    file_value = mapping.get(file_key)
    has_value = value is not None
    has_file = file_value is not None
    if not has_value and not has_file:
        return None
    if has_value == has_file:
        raise ConfigurationError(
            f"{label} must define exactly one of {value_key!r} or {file_key!r}. "
            f"For example, configure one {label}.{value_key} or {label}.{file_key}."
        )
    if has_value:
        if not isinstance(value, str) or not value:
            raise ConfigurationError(f"{label}.{value_key} must be a non-empty string.")
        return SecretSource(value=value)
    if not isinstance(file_value, str) or not file_value:
        raise ConfigurationError(f"{label}.{file_key} must be a non-empty string.")
    return SecretSource(file=Path(file_value).expanduser())


def _secret_source(
    mapping: Mapping[str, Any],
    value_key: str,
    file_key: str,
    label: str,
) -> SecretSource:
    value = mapping.get(value_key)
    file_value = mapping.get(file_key)
    has_value = value is not None
    has_file = file_value is not None
    if has_value == has_file:
        raise ConfigurationError(
            f"{label} must define exactly one of {value_key!r} or {file_key!r}. "
            f"For example, configure one {label}.{value_key} or {label}.{file_key}."
        )
    if has_value:
        if not isinstance(value, str) or not value:
            raise ConfigurationError(f"{label}.{value_key} must be a non-empty string.")
        return SecretSource(value=value)
    if not isinstance(file_value, str) or not file_value:
        raise ConfigurationError(
            f"{label}.{file_key} must be a non-empty string."
        )
    return SecretSource(file=Path(file_value).expanduser())


def _mapping(
    raw: Mapping[str, Any],
    key: str,
    *,
    required: bool = True,
) -> Mapping[str, Any]:
    value = raw.get(key)
    if value is None:
        if required:
            raise ConfigurationError(f"Missing required configuration section: {key}")
        return {}
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"Configuration section {key!r} must be a YAML mapping.")
    return value


def _required_string(mapping: Mapping[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{label} must be a non-empty string.")
    return value.strip()



def _required_identifier(mapping: Mapping[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if value is None:
        raise ConfigurationError(f"{label} must be provided.")
    text = str(value).strip()
    if not text:
        raise ConfigurationError(f"{label} must not be empty.")
    return text

def _guild_ids(value: Any, label: str) -> tuple[int, ...]:
    values = value if isinstance(value, (list, tuple)) else [value]
    if not values or values == [None]:
        raise ConfigurationError(f"{label} is required.")
    try:
        result = tuple(sorted({int(item) for item in values}))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{label} must contain numeric Discord guild IDs.") from exc
    if not result:
        raise ConfigurationError(f"{label} must contain at least one guild ID.")
    return result


def _nonnegative_float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{label} must be a non-negative number.") from exc
    if result < 0:
        raise ConfigurationError(f"{label} must be a non-negative number.")
    return result


def _resolve_path(value: Path, base_dir: Path) -> Path:
    if value.is_absolute():
        return value
    return (base_dir / value).resolve()
