"""Human-authored application configuration for Archive-Sync Engine.

This module defines the setup configuration used before an Archive exists or
while selecting resources for an existing Archive. It deliberately remains at
the application boundary: canonical Archive identities and synchronization
state are not serialized into this configuration format.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping
import re

import yaml

from archive_sync_engine.adapters.fluxer import (
    FluxerCustomEmojiMapping,
    FluxerIdentityMapping,
)


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
class SetupCustomEmojiMapping:
    """Map a stable source custom emoji ID to an existing Fluxer emoji."""

    source_platform: Literal["discord"]
    source_emoji_id: str
    fluxer_emoji_id: str
    fluxer_emoji_name: str

    def resolve(self) -> FluxerCustomEmojiMapping:
        return FluxerCustomEmojiMapping(
            source_emoji_id=self.source_emoji_id,
            fluxer_emoji_id=self.fluxer_emoji_id,
            fluxer_emoji_name=self.fluxer_emoji_name,
        )


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
    fluxer_username: str | None
    fluxer_auth: SecretSource | None
    discord_auth: SecretSource | None = None
    fluxer_bot: bool = False

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
        if self.fluxer_bot:
            return FluxerIdentityMapping(
                username=self.canonical_identity_key,
                fluxer_auth_key=None,
                fluxer_username=self.fluxer_username,
            )

        if self.fluxer_auth is None:
            raise ConfigurationError(
                f"No Fluxer authentication is configured for Discord user "
                f"{self.external_user_id}. Set fluxer_bot: true if this identity "
                "should intentionally use the default Fluxer bot account."
            )
        fluxer_username = _required_fluxer_username(
            {"fluxer_username": self.fluxer_username},
            f"Fluxer username for Discord user {self.external_user_id}",
        )
        return FluxerIdentityMapping(
            username=self.canonical_identity_key,
            fluxer_auth_key=self.fluxer_auth.resolve(
                base_dir=base_dir,
                label=f"Fluxer auth for Discord user {self.external_user_id}",
            ),
            fluxer_username=fluxer_username,
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
    custom_emoji_mappings: tuple[FluxerCustomEmojiMapping, ...]


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
    custom_emoji_mappings: tuple[SetupCustomEmojiMapping, ...] = ()
    between_messages_seconds: float = 0.0
    between_channels_seconds: float = 0.0
    compatibility_mode: bool = False

    @property
    def config_directory(self) -> Path:
        return self.source_config_path.parent

    def resolved_archive_path(self) -> Path:
        return _resolve_path(self.archive_path, self.config_directory)

    def resolve_input_scope(self, adapter: str) -> tuple[str, ...]:
        normalized = str(adapter).strip().lower()
        if not normalized:
            raise ConfigurationError("Input adapter must not be empty.")
        if self.input_adapter == normalized and self.input_scope:
            return self.input_scope
        if normalized == "discord" and self.discord_guild_ids:
            return tuple(str(value) for value in self.discord_guild_ids)
        if normalized == "fluxer" and self.fluxer_guild_id:
            return (self.fluxer_guild_id,)
        return ()

    def resolve_destination_scope(self, adapter: str) -> tuple[str, ...]:
        normalized = str(adapter).strip().lower()
        if not normalized:
            raise ConfigurationError("Destination adapter must not be empty.")
        if normalized == "fluxer" and self.fluxer_guild_id:
            return (self.fluxer_guild_id,)
        return ()

    def resolve_credentials(
        self,
        *,
        required_adapters: Iterable[str] | None = None,
        require_discord: bool | None = None,
        require_fluxer: bool | None = None,
    ) -> ResolvedSetupCredentials:
        """Resolve only the credentials required by the selected adapters.

        ``required_adapters`` is the preferred adapter-neutral API.  The
        legacy ``require_discord``/``require_fluxer`` switches remain for
        existing workflows and callers.  Secrets belonging to adapters that
        are not selected are deliberately not resolved.
        """
        if required_adapters is not None and (
            require_discord is not None or require_fluxer is not None
        ):
            raise ConfigurationError(
                "required_adapters cannot be combined with require_discord "
                "or require_fluxer."
            )
        if required_adapters is None:
            required = set()
            if require_discord is None:
                require_discord = True
            if require_fluxer is None:
                require_fluxer = True
            if require_discord:
                required.add("discord")
            if require_fluxer:
                required.add("fluxer")
            if not required:
                raise ConfigurationError("At least one adapter must be selected.")
        else:
            required = {str(adapter).strip().lower() for adapter in required_adapters}
            if not required:
                raise ConfigurationError("At least one adapter must be selected.")

        base_dir = self.config_directory
        discord_token: str | None = None
        fluxer_token = ""
        discord_user_auth: dict[str, str] = {}
        fluxer_user_auth: dict[str, str] = {}
        identity_mappings: tuple[FluxerIdentityMapping, ...] = ()
        custom_emoji_mappings: tuple[FluxerCustomEmojiMapping, ...] = ()

        if "discord" in required:
            if self.discord_token is None:
                raise ConfigurationError(
                    "Discord configuration is required but was not provided."
                )
            discord_token = self.discord_token.resolve(
                base_dir=base_dir,
                label="Discord token",
            )
            discord_user_auth = {
                mapping.discord_user_id: mapping.resolve_discord_auth(base_dir=base_dir)
                for mapping in self.identity_mappings
                if mapping.discord_auth is not None
            }

        if "fluxer" in required:
            if self.fluxer_token is None:
                raise ConfigurationError(
                    "Fluxer configuration is required but was not provided."
                )
            fluxer_token = self.fluxer_token.resolve(
                base_dir=base_dir,
                label="Fluxer token",
            )
            fluxer_user_auth = {}
            for mapping in self.fluxer_user_mappings:
                if mapping.fluxer_auth is None:
                    continue
                fluxer_user_auth[mapping.fluxer_user_id] = mapping.fluxer_auth.resolve(
                    base_dir=base_dir,
                    label=f"Fluxer auth for Fluxer user {mapping.fluxer_user_id}",
                )
            identity_mappings = tuple(
                mapping.resolve(base_dir=base_dir)
                for mapping in self.identity_mappings
            )
            custom_emoji_mappings = tuple(
                mapping.resolve() for mapping in self.custom_emoji_mappings
            )

        return ResolvedSetupCredentials(
            discord_token=discord_token,
            fluxer_token=fluxer_token,
            discord_user_auth=discord_user_auth,
            fluxer_user_auth=fluxer_user_auth,
            identity_mappings=identity_mappings,
            custom_emoji_mappings=custom_emoji_mappings,
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
    required_adapters: Iterable[str] | None = None,
    require_discord: bool | None = None,
    require_fluxer: bool | None = None,
) -> SetupConfiguration:
    """Load configuration with adapter-specific requirements.

    ``required_adapters`` is the preferred adapter-neutral API.  The legacy
    concrete-platform switches remain supported for compatibility.
    """
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

    if required_adapters is not None and (
        require_discord is not None or require_fluxer is not None
    ):
        raise ConfigurationError(
            "required_adapters cannot be combined with require_discord "
            "or require_fluxer."
        )
    if required_adapters is None:
        if require_discord is None:
            require_discord = True
        if require_fluxer is None:
            require_fluxer = True
        required = set()
        if require_discord:
            required.add("discord")
        if require_fluxer:
            required.add("fluxer")
    else:
        required = {str(adapter).strip().lower() for adapter in required_adapters}
        if not required:
            raise ConfigurationError("At least one adapter must be selected.")

    archive = _mapping(raw, "archive")
    discord = _mapping(raw, "discord", required="discord" in required)
    fluxer = _mapping(raw, "fluxer", required="fluxer" in required)
    delays = _mapping(raw, "delays", required=False)
    export = _mapping(raw, "export", required=False)
    input_config = _mapping(raw, "input", required=False)
    mappings = _mapping(raw, "user_mappings", required=False)
    emoji_mappings = _mapping(raw, "emoji_mappings", required=False)

    archive_path = _required_string(archive, "path", "archive.path")

    input_adapter_value = input_config.get("adapter")
    if input_adapter_value is None:
        # A source-only configuration may omit the explicit input section.
        # Prefer the sole configured platform; retain Discord as the default
        # when both platform sections are present for backward compatibility.
        configured_adapters = [
            name for name, section in (("discord", discord), ("fluxer", fluxer))
            if section
        ]
        input_adapter = configured_adapters[0] if len(configured_adapters) == 1 else "discord"
    else:
        input_adapter = _required_identifier(
            input_config, "adapter", "input.adapter"
        ).lower()

    input_scope_value = input_config.get("scope")
    if input_scope_value is None:
        if input_adapter == "discord" and "discord" in required:
            input_scope = tuple(
                str(value)
                for value in _guild_ids(
                    discord.get("guild_id")
                    if discord.get("guild_id") is not None
                    else discord.get("guild_ids"),
                    "discord.guild_id",
                )
            )
        elif input_adapter == "fluxer" and "fluxer" in required:
            input_scope = (
                _required_identifier(fluxer, "server_id", "fluxer.server_id")
                if fluxer.get("server_id") is not None
                else _required_identifier(fluxer, "guild_id", "fluxer.guild_id")
            ,)
        else:
            input_scope = ()
    else:
        if not isinstance(input_scope_value, (list, tuple)):
            raise ConfigurationError("input.scope must be a YAML sequence.")
        input_scope = tuple(str(value).strip() for value in input_scope_value)
        if any(not value for value in input_scope):
            raise ConfigurationError("input.scope values must not be empty.")
    discord_token = (
        _secret_source(discord, "token", "token_file", "discord")
        if "discord" in required else _optional_secret_source(
            discord, "token", "token_file", "discord"
        )
    )
    fluxer_token = (
        _secret_source(fluxer, "token", "token_file", "fluxer")
        if "fluxer" in required else _optional_secret_source(
            fluxer, "token", "token_file", "fluxer"
        )
    )

    discord_guild_value = discord.get("guild_id")
    if discord_guild_value is None:
        discord_guild_value = discord.get("guild_ids")
    discord_guild_ids = (
        _guild_ids(discord_guild_value, "discord.guild_id")
        if "discord" in required else ()
    )

    fluxer_guild_value = fluxer.get("server_id")
    if fluxer_guild_value is None:
        fluxer_guild_value = fluxer.get("guild_id")
    fluxer_guild_id = (
        _required_identifier(
            {"value": fluxer_guild_value}, "value", "fluxer.server_id"
        )
        if "fluxer" in required and fluxer_guild_value is not None
        else (str(fluxer_guild_value) if fluxer_guild_value is not None else None)
    )

    identity_mappings, fluxer_user_mappings = _parse_user_mappings(
        mappings,
        validate_fluxer_fields="fluxer" in required,
    )
    custom_emoji_mappings = _parse_custom_emoji_mappings(emoji_mappings)

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
        custom_emoji_mappings=custom_emoji_mappings,
        between_messages_seconds=between_messages,
        between_channels_seconds=between_channels,
        compatibility_mode=_boolean(export.get("compatibility_mode", False), "export.compatibility_mode"),
    )


def _parse_custom_emoji_mappings(value: Mapping[str, Any]) -> tuple[SetupCustomEmojiMapping, ...]:
    discord_entries = value.get("discord")
    if discord_entries is None:
        return ()
    if not isinstance(discord_entries, Mapping):
        raise ConfigurationError("emoji_mappings.discord must be a YAML mapping.")

    mappings: list[SetupCustomEmojiMapping] = []
    seen: set[str] = set()
    for source_id, raw_mapping in discord_entries.items():
        source_emoji_id = _stable_id(source_id, "emoji_mappings.discord", "emoji ID")
        if source_emoji_id in seen:
            raise ConfigurationError(
                f"emoji_mappings.discord contains duplicate source emoji ID {source_emoji_id!r}."
            )
        seen.add(source_emoji_id)
        if not isinstance(raw_mapping, Mapping):
            raise ConfigurationError(
                f"emoji_mappings.discord.{source_emoji_id} must be a YAML mapping."
            )
        fluxer_emoji_id = _required_identifier(
            raw_mapping, "fluxer_emoji_id",
            f"emoji_mappings.discord.{source_emoji_id}.fluxer_emoji_id",
        )
        fluxer_emoji_name = _required_string(
            raw_mapping, "fluxer_emoji_name",
            f"emoji_mappings.discord.{source_emoji_id}.fluxer_emoji_name",
        )
        mappings.append(
            SetupCustomEmojiMapping(
                source_platform="discord",
                source_emoji_id=source_emoji_id,
                fluxer_emoji_id=fluxer_emoji_id,
                fluxer_emoji_name=fluxer_emoji_name,
            )
        )
    return tuple(mappings)


def _parse_user_mappings(
    value: Mapping[str, Any],
    *,
    validate_fluxer_fields: bool = True,
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

        fluxer_bot = _optional_bool(
            raw_mapping,
            "fluxer_bot",
            f"user_mappings.discord.{user_id}.fluxer_bot",
        )
        if fluxer_bot:
            fluxer_username = _optional_string(
                raw_mapping,
                "fluxer_username",
                f"user_mappings.discord.{user_id}.fluxer_username",
            )
            fluxer_auth = None
        elif validate_fluxer_fields:
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
        else:
            fluxer_username = _optional_string(
                raw_mapping,
                "fluxer_username",
                f"user_mappings.discord.{user_id}.fluxer_username",
            )
            fluxer_auth = _optional_secret_source(
                raw_mapping,
                "fluxer_auth_key",
                "fluxer_auth_key_file",
                f"user_mappings.discord.{user_id}",
            )
        if fluxer_bot and (
            raw_mapping.get("fluxer_auth_key") is not None
            or raw_mapping.get("fluxer_auth_key_file") is not None
        ):
            raise ConfigurationError(
                f"user_mappings.discord.{user_id} must not configure Fluxer "
                "authentication when fluxer_bot is true."
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
                fluxer_bot=fluxer_bot,
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

        fluxer_bot = _optional_bool(
            raw_mapping,
            "fluxer_bot",
            f"user_mappings.fluxer.{user_id}.fluxer_bot",
        )
        if fluxer_bot:
            fluxer_username = _optional_string(
                raw_mapping,
                "fluxer_username",
                f"user_mappings.fluxer.{user_id}.fluxer_username",
            )
            if raw_mapping.get("fluxer_auth_key") is not None or raw_mapping.get("fluxer_auth_key_file") is not None:
                raise ConfigurationError(
                    f"user_mappings.fluxer.{user_id} must not configure Fluxer "
                    "authentication when fluxer_bot is true."
                )
            fluxer_auth = None
        elif validate_fluxer_fields:
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
        else:
            fluxer_username = _optional_string(
                raw_mapping,
                "fluxer_username",
                f"user_mappings.fluxer.{user_id}.fluxer_username",
            )
            fluxer_auth = _optional_secret_source(
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


def _stable_id(value: Any, path: str, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ConfigurationError(f"{path} {label} must not be empty.")
    return text


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


def _optional_bool(
    mapping: Mapping[str, Any],
    key: str,
    label: str,
) -> bool:
    value = mapping.get(key, False)
    if not isinstance(value, bool):
        raise ConfigurationError(f"{label} must be true or false when provided.")
    return value


def _optional_string(
    mapping: Mapping[str, Any],
    key: str,
    label: str,
) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{label} must be a non-empty string when provided.")
    return value.strip()


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


def _boolean(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigurationError(f"{label} must be a boolean.")


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
