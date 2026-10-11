"""Runtime construction and lifecycle for Discord source clients.

The canonical Discord source adapter consumes an already-created discord.py
client.  This module owns the application-level authentication and lifecycle
boundary so callers do not need to know how discord.py establishes its HTTP
session.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Mapping, Callable, Awaitable, TypeVar

from archive_sync_engine.adapters.exceptions import AdapterError
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.importer.canonical_coordinator import CanonicalImportCoordinator, ImportReport

from .source import DiscordSourceAdapter
from ...importer import ImportProgress

_T = TypeVar("_T")
CLIENT_CLOSE_TIMEOUT_SECONDS = 15.0


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

    def create(
        self,
        config: DiscordClientConfig,
        *,
        runner: Callable[[Awaitable[_T]], _T] | None = None,
    ) -> Any:
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
            self._login(client, config.token, runner=runner)
            return client
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(
                "Failed to construct or authenticate the Discord client."
            ) from exc

    @staticmethod
    def _login(
        client: Any,
        token: str,
        *,
        runner: Callable[[Awaitable[Any]], Any] | None = None,
    ) -> None:
        login = getattr(client, "login", None)
        if login is None:
            raise AdapterError("Discord client does not expose login().")

        # discord.py's login() is asynchronous.  The source adapter itself is
        # synchronous, so authentication is completed once at runtime setup.
        import asyncio

        if runner is not None:
            runner(login(token))
        else:
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
        loop = asyncio.new_event_loop()
        previous_loop = None
        try:
            try:
                previous_loop = asyncio.get_event_loop()
            except RuntimeError:
                previous_loop = None
            asyncio.set_event_loop(loop)
            client = factory.create(config, runner=loop.run_until_complete)
            return cls(
                client,
                guild_ids=config.guild_ids,
                loop=loop,
                previous_loop=previous_loop,
                incremental_lookback_days=request.adapter_config.get("incremental_lookback_days", 7),
            )
        except Exception:
            loop.close()
            if previous_loop is not None and not previous_loop.is_closed():
                asyncio.set_event_loop(previous_loop)
            else:
                asyncio.set_event_loop(None)
            raise
    """Own an authenticated Discord client and expose its canonical adapter."""

    def __init__(
        self,
        client: Any,
        *,
        guild_ids: tuple[int | str, ...],
        loop: asyncio.AbstractEventLoop | None = None,
        previous_loop: asyncio.AbstractEventLoop | None = None,
        incremental_lookback_days: int | float = 7,
    ) -> None:
        self._client = client
        self._guild_ids = tuple(guild_ids)
        self.adapter = DiscordSourceAdapter(
            client,
            self._guild_ids,
        )
        self.adapter.set_incremental_refresh_lookback_days(incremental_lookback_days)
        self._loop = loop
        self._previous_loop = previous_loop
        if loop is not None:
            self.adapter.set_runner(loop.run_until_complete)
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
        on_status: Callable[[ImportProgress], None] | None = None,
        between_messages_seconds: float = 0.0,
        between_channels_seconds: float = 0.0,
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

        run_kwargs: dict[str, Any] = {
            "resume": resume,
            "on_status": on_status,
        }
        # Preserve compatibility with coordinator test doubles and older
        # adapters when the configured delays are both zero.
        if between_messages_seconds or between_channels_seconds:
            run_kwargs.update(
                between_messages_seconds=between_messages_seconds,
                between_channels_seconds=between_channels_seconds,
            )
        progress_setter = getattr(
            self.adapter,
            "set_identity_scan_progress_callback",
            None,
        )
        if callable(progress_setter) and on_status is not None:
            progress_setter(
                lambda current, detail: on_status(
                    ImportProgress(
                        phase="identity_scan",
                        current=current,
                        detail=detail,
                    )
                )
            )
        try:
            return CanonicalImportCoordinator(
                archive_paths,
            ).run(
                self.adapter,
                **run_kwargs,
            )
        finally:
            if callable(progress_setter):
                progress_setter(None)

    def close(self) -> None:
        """Close the Discord client and its runtime-owned event loop."""
        if self._closed:
            return

        close = getattr(self._client, "close", None)
        if close is None:
            raise AdapterError("Discord client does not expose close().")

        try:
            # asyncio.wait_for() may exceed its timeout while waiting for a
            # cancellation-resistant coroutine to finish cancelling. Use
            # asyncio.wait() instead: its timeout bounds the wait itself.
            loop = self._loop
            if loop is None:
                loop = asyncio.new_event_loop()
                self._loop = loop
            close_task = loop.create_task(close())
            _, pending = loop.run_until_complete(
                asyncio.wait({close_task}, timeout=CLIENT_CLOSE_TIMEOUT_SECONDS)
            )
            if pending:
                close_task.cancel()
                # Give cooperative clients a brief opportunity to clean up,
                # but never let cancellation delay process termination.
                loop.run_until_complete(asyncio.wait({close_task}, timeout=0.25))
                raise AdapterError(
                    "Timed out after "
                    f"{CLIENT_CLOSE_TIMEOUT_SECONDS:g} seconds while closing the Discord client."
                )
            close_task.result()
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError("Failed to close the Discord client.") from exc
        finally:
            self._closed = True
            if self._loop is not None:
                self._loop.close()
                if self._previous_loop is not None and not self._previous_loop.is_closed():
                    asyncio.set_event_loop(self._previous_loop)
                else:
                    asyncio.set_event_loop(None)

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
