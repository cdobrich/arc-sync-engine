"""Runtime construction and lifecycle for Discord source clients.

The canonical Discord source adapter consumes an already-created discord.py
client.  This module owns the application-level authentication and lifecycle
boundary so callers do not need to know how discord.py establishes its HTTP
session.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any, Mapping, Callable

from archive_sync_engine.adapters.exceptions import AdapterError
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.importer.canonical_coordinator import CanonicalImportCoordinator, ImportReport

from .source import DiscordSourceAdapter


@dataclass(frozen=True, slots=True)
class DiscordClientConfig:
    """Configuration for one authenticated Discord source client."""

    token: str
    guild_ids: tuple[int, ...]
    intents: Any | None = None

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("Discord client token must not be empty.")
        if not self.guild_ids:
            raise ValueError("Discord client configuration requires guild IDs.")
        normalized = tuple(sorted({int(guild_id) for guild_id in self.guild_ids}))
        object.__setattr__(self, "guild_ids", normalized)


class DiscordClientFactory:
    """Construct authenticated discord.py clients without starting a gateway."""

    def __init__(
        self,
        *,
        importer: Callable[[], ModuleType] | None = None,
        client_builder: Callable[..., Any] | None = None,
    ) -> None:
        self._importer = importer or self._import_discord
        self._client_builder = client_builder

    def create(self, config: DiscordClientConfig) -> Any:
        """Create and authenticate one discord.py client."""
        module = self._load_discord()

        intents = config.intents
        if intents is None:
            intents_type = getattr(module, "Intents", None)
            if intents_type is None:
                raise AdapterError(
                    "The installed discord.py package does not expose Intents."
                )
            intents = intents_type.none()
            intents.guilds = True
            intents.members = True
            intents.message_content = True

        builder = self._client_builder
        if builder is None:
            client_type = getattr(module, "Client", None)
            if client_type is None:
                raise AdapterError(
                    "The installed discord.py package does not expose Client."
                )
            builder = client_type

        try:
            client = builder(intents=intents)
            self._login(client, config.token)
            return client
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(
                "Failed to construct or authenticate the Discord client."
            ) from exc

    @staticmethod
    def _login(client: Any, token: str) -> None:
        login = getattr(client, "login", None)
        if login is None:
            raise AdapterError("Discord client does not expose login().")

        # discord.py's login() is asynchronous.  The source adapter itself is
        # synchronous, so authentication is completed once at runtime setup.
        import asyncio

        asyncio.run(login(token))

    def _load_discord(self) -> ModuleType:
        try:
            return self._importer()
        except Exception as exc:
            raise AdapterError(
                "The optional discord.py dependency could not be imported."
            ) from exc

    @staticmethod
    def _import_discord() -> ModuleType:
        import discord

        return discord


class DiscordSourceRuntime:
    """Own an authenticated Discord client and expose its canonical adapter."""

    @classmethod
    def from_source_runtime_request(cls, request: "SourceRuntimeRequest") -> "DiscordSourceRuntime":
        """Construct the Discord source runtime from an adapter-neutral request."""
        from archive_sync_engine.adapters.source_runtime_request import SourceRuntimeRequest

        if request.adapter != "discord":
            raise AdapterError("DiscordSourceRuntime requires the discord source adapter.")
        try:
            config = request.adapter_config["discord"]
        except KeyError as exc:
            raise AdapterError("Missing runtime configuration for adapter 'discord'.") from exc
        if not isinstance(config, DiscordClientConfig):
            raise AdapterError("Runtime configuration for 'discord' is invalid.")
        factory = request.adapter_config.get("discord_client_factory")
        if factory is None:
            factory = DiscordClientFactory()
        client = factory.create(config)
        return cls(client, guild_ids=config.guild_ids)
    """Own an authenticated Discord client and expose its canonical adapter."""

    def __init__(
        self,
        client: Any,
        *,
        guild_ids: tuple[int | str, ...],
    ) -> None:
        self._client = client
        self._guild_ids = tuple(guild_ids)
        self.adapter = DiscordSourceAdapter(
            client,
            self._guild_ids,
        )
        self._closed = False

    @property
    def input_scope(self) -> tuple[str, ...]:
        """Return the configured source scope in its canonical string form."""
        return tuple(str(guild_id) for guild_id in self._guild_ids)

    def import_to_archive(
        self,
        archive_paths: ArchivePaths,
        *,
        resume: bool = False,
    ) -> ImportReport:
        """Import the authenticated Discord source into an Archive Package.

        The runtime owns only the Discord client/source boundary.
        Canonical import lifecycle, checkpointing, and Archive persistence
        remain owned by ``CanonicalImportCoordinator``.
        """
        if self._closed:
            raise AdapterError(
                "Cannot import from a closed Discord source runtime."
            )

        return CanonicalImportCoordinator(
            archive_paths,
        ).run(
            self.adapter,
            resume=resume,
        )

    def close(self) -> None:
        """Close the discord.py HTTP/session resources synchronously."""
        if self._closed:
            return

        close = getattr(self._client, "close", None)
        if close is None:
            raise AdapterError("Discord client does not expose close().")

        import asyncio

        try:
            asyncio.run(close())
        except Exception as exc:
            raise AdapterError("Failed to close the Discord client.") from exc
        finally:
            self._closed = True

    def __enter__(self) -> "DiscordSourceRuntime":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


def build_discord_source_runtime_config(
    credentials: Any,
    scope: tuple[str, ...],
    overrides: Mapping[str, Any],
) -> DiscordClientConfig:
    """Build Discord runtime configuration behind the source registry boundary."""
    token = overrides.get("token") or getattr(credentials, "discord_token", None)
    if not token:
        raise AdapterError("Discord source credentials are missing.")
    try:
        guild_ids = tuple(int(value) for value in scope)
    except (TypeError, ValueError) as exc:
        raise AdapterError("Discord source scope must contain numeric guild IDs.") from exc
    return DiscordClientConfig(token=token, guild_ids=guild_ids)
