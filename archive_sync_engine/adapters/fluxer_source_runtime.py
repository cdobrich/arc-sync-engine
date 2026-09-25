"""Runtime construction and lifecycle for Fluxer source imports."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from archive_sync_engine.adapters.exceptions import AdapterError
from archive_sync_engine.archive.paths import ArchivePaths
from archive_sync_engine.importer.canonical_coordinator import CanonicalImportCoordinator, ImportReport
from archive_sync_engine.importer.progress import ImportProgress

from .fluxer_runtime import FluxerClientConfig, FluxerHttpClientFactory
from .fluxer_source import FluxerSourceAdapter


class FluxerHttpSourceClient:
    """Translate Fluxer REST HTTPClient operations into source operations."""

    def __init__(
        self,
        http_client: Any,
        *,
        token: str | None = None,
        emoji_asset_base_url: str | None = None,
    ) -> None:
        self._http = http_client
        self._token = token
        self._emoji_asset_base_url = self._normalize_emoji_asset_base_url(
            emoji_asset_base_url or self._derive_emoji_asset_base_url(http_client)
        )

    async def _request(self, method: str, path: str, **route_params: Any) -> Any:
        route = self._http._route(method, path, **route_params)
        return await self._http.request(route)

    async def _request_page(self, method: str, path: str, *, query: Mapping[str, Any], **route_params: Any) -> Any:
        route = self._http._route(method, path, **route_params)
        return await self._http.request(route, params=dict(query))

    async def get_guild_channels(self, guild_id: str) -> list[Any]:
        result = await self._request("GET", "/guilds/{guild_id}/channels", guild_id=guild_id)
        return list(result or ())

    async def get_channel_messages(self, channel_id: str, *, before: str | None = None) -> list[Any]:
        query = {"limit": 100}
        if before is not None:
            query["before"] = before
        result = await self._request_page(
            "GET",
            "/channels/{channel_id}/messages",
            query=query,
            channel_id=channel_id,
        )
        return list(result or ())

    async def get_pinned_message_ids(self, channel_id: str) -> set[str]:
        """Return all currently pinned message IDs for one channel.

        Message-history payloads are not a reliable source of pin state across
        Fluxer deployments: some omit the ``pinned`` field entirely.  The pin
        collection is therefore the source-of-truth for imports.  Prefer the
        current ``messages/pins`` endpoint and fall back to the deprecated
        ``pins`` endpoint only when the server reports that the current route
        does not exist.
        """
        try:
            payload = await self._request(
                "GET",
                "/channels/{channel_id}/messages/pins",
                channel_id=channel_id,
            )
            return self._pin_ids_from_payload(payload)
        except Exception as exc:
            if not self._is_not_found(exc):
                raise
            payload = await self._request(
                "GET",
                "/channels/{channel_id}/pins",
                channel_id=channel_id,
            )
            return self._pin_ids_from_payload(payload)

    @staticmethod
    def _pin_ids_from_payload(payload: Any) -> set[str]:
        """Extract message IDs from every supported Fluxer pin envelope.

        Fluxer-compatible deployments have returned the pin collection under
        several top-level keys.  The canonical source import must treat the
        complete pin collection as authoritative, so an unrecognized envelope
        must not silently become an empty pin set.
        """
        if isinstance(payload, Mapping):
            for key in ("items", "pins", "data", "results", "messages"):
                if key in payload:
                    payload = payload[key]
                    break
        else:
            for key in ("items", "pins", "data", "results", "messages"):
                value = getattr(payload, key, None)
                if value is not None:
                    payload = value
                    break

        if not isinstance(payload, (list, tuple)):
            return set()

        ids: set[str] = set()
        for item in payload:
            if isinstance(item, Mapping):
                message = item.get("message")
                candidate = message if isinstance(message, Mapping) else item
                message_id = candidate.get("id") or item.get("message_id")
            else:
                message = getattr(item, "message", None)
                candidate = message if message is not None else item
                message_id = getattr(candidate, "id", None)
                if message_id is None:
                    message_id = getattr(item, "message_id", None)
            if message_id is not None:
                ids.add(str(message_id))
        return ids

    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        code = getattr(exc, "code", None)
        if code is None:
            code = getattr(exc, "status", None)
        return code == 404 or "404" in str(exc)

    async def get_reaction_users(self, channel_id: str, message_id: str, emoji: str) -> list[Any]:
        result = await self._request(
            "GET",
            "/channels/{channel_id}/messages/{message_id}/reactions/{emoji}",
            channel_id=channel_id,
            message_id=message_id,
            emoji=emoji,
        )
        return list(result or ())

    async def get_guild_emojis(self, guild_id: str) -> list[Any]:
        # fluxer.py's Emoji model intentionally contains metadata only and
        # does not expose a readable asset URL.  The Archive, however, needs
        # the actual bytes in order to preserve source custom emojis.  Keep
        # the URL construction here, at the platform/runtime boundary, so
        # the canonical source adapter remains independent of Fluxer's CDN.
        emojis = list(await self._http.get_guild_emojis(guild_id))
        normalized: list[Any] = []
        for emoji in emojis:
            emoji_id = self._emoji_field(emoji, "id")
            if emoji_id is None:
                normalized.append(emoji)
                continue

            if self._emoji_has_asset_url(emoji):
                normalized.append(emoji)
                continue

            # fluxer.py intentionally exposes a metadata-only Emoji model.
            # Ask the REST endpoint for the individual emoji representation as
            # a second source of truth before falling back to a constructed CDN
            # URL.  Some Fluxer deployments expose the actual asset URL there.
            metadata = await self._fetch_guild_emoji_metadata(guild_id, str(emoji_id))
            metadata_url = self._find_emoji_asset_url(metadata)
            if metadata_url:
                normalized.append(self._with_emoji_url(emoji, metadata_url))
                continue

            asset_url = f"{self._emoji_asset_base_url}/emojis/{emoji_id}"
            normalized.append(self._with_emoji_url(emoji, asset_url))
        return normalized

    @staticmethod
    def _emoji_field(emoji: Any, name: str, default: Any = None) -> Any:
        if isinstance(emoji, dict):
            return emoji.get(name, default)
        return getattr(emoji, name, default)

    @classmethod
    def _emoji_has_asset_url(cls, emoji: Any) -> bool:
        return bool(
            cls._emoji_field(emoji, "url")
            or cls._emoji_field(emoji, "proxy_url")
            or cls._emoji_field(emoji, "image_url")
            or cls._emoji_field(emoji, "asset_url")
        )

    @classmethod
    def _find_emoji_asset_url(cls, value: Any) -> str | None:
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
        if isinstance(value, Mapping):
            for key in ("url", "proxy_url", "image_url", "asset_url"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                    return candidate
            for candidate in value.values():
                found = cls._find_emoji_asset_url(candidate)
                if found:
                    return found
        if isinstance(value, (list, tuple)):
            for candidate in value:
                found = cls._find_emoji_asset_url(candidate)
                if found:
                    return found
        return None

    def _with_emoji_url(self, emoji: Any, asset_url: str) -> Any:
        if isinstance(emoji, dict):
            result = dict(emoji)
            result["url"] = asset_url
            return result
        try:
            setattr(emoji, "url", asset_url)
            return emoji
        except (AttributeError, TypeError):
            return {
                "id": self._emoji_field(emoji, "id"),
                "name": self._emoji_field(emoji, "name"),
                "animated": bool(self._emoji_field(emoji, "animated", False)),
                "url": asset_url,
            }

    async def _fetch_guild_emoji_metadata(self, guild_id: str, emoji_id: str) -> Any:
        if not self._token:
            return None
        api_url = str(getattr(self._http, "api_url", "https://api.fluxer.app/v1")).rstrip("/")
        url = f"{api_url}/guilds/{guild_id}/emojis/{emoji_id}"

        def read() -> Any:
            request = Request(
                url,
                headers={
                    "Authorization": f"Bot {self._token}",
                    "Accept": "application/json",
                    "User-Agent": "Archive-Sync Engine",
                },
            )
            with urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))

        try:
            return await asyncio.to_thread(read)
        except Exception as exc:
            logging.getLogger(__name__).debug(
                "Unable to retrieve raw Fluxer emoji metadata for %s/%s: %s",
                guild_id,
                emoji_id,
                exc,
            )
            return None

    @staticmethod
    def _normalize_emoji_asset_base_url(value: str) -> str:
        normalized = str(value).strip().rstrip("/")
        if not normalized:
            raise ValueError("Fluxer emoji asset base URL must not be empty.")
        return normalized

    @staticmethod
    def _derive_emoji_asset_base_url(http_client: Any) -> str:
        api_url = str(getattr(http_client, "api_url", "https://api.fluxer.app/v1"))
        parsed = urlparse(api_url)
        if parsed.scheme and parsed.netloc == "api.fluxer.app":
            return "https://fluxerstatic.com"
        if parsed.scheme and parsed.netloc:
            # Self-hosted instances commonly expose API and media from the
            # same public origin.  A runtime request can override this with a
            # dedicated CDN base when an installation uses a separate host.
            return f"{parsed.scheme}://{parsed.netloc}"
        return "https://fluxerstatic.com"

    async def download_url(self, url: str) -> bytes:
        def read() -> bytes:
            request = Request(url, headers={"User-Agent": "Archive-Sync Engine"})
            with urlopen(request, timeout=60) as response:
                return response.read()
        return await asyncio.to_thread(read)


@dataclass(frozen=True, slots=True)
class FluxerSourceRuntimeConfig:
    """Configuration for one authenticated Fluxer source client."""

    token: str
    guild_ids: tuple[str, ...]
    api_url: str | None = None
    emoji_asset_base_url: str | None = None
    max_retries: int = 4
    retry_forever: bool = False

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("Fluxer source token must not be empty.")
        if not self.guild_ids:
            raise ValueError("Fluxer source configuration requires guild IDs.")
        normalized = tuple(sorted({str(value) for value in self.guild_ids}))
        object.__setattr__(self, "guild_ids", normalized)
        if self.max_retries < 0:
            raise ValueError("Fluxer source max_retries must be non-negative.")


class FluxerSourceRuntime:
    """Own an authenticated Fluxer HTTP client and expose its source adapter."""

    @classmethod
    def from_source_runtime_request(cls, request: "SourceRuntimeRequest") -> "FluxerSourceRuntime":
        from archive_sync_engine.adapters.source_runtime_request import SourceRuntimeRequest
        if request.adapter != "fluxer":
            raise AdapterError("FluxerSourceRuntime requires the fluxer source adapter.")
        config = request.adapter_config.get("fluxer")
        if not isinstance(config, FluxerSourceRuntimeConfig):
            raise AdapterError("Runtime configuration for 'fluxer' source is invalid.")
        factory = request.adapter_config.get("fluxer_client_factory") or FluxerHttpClientFactory()
        return cls(config, factory=factory)

    def __init__(self, config: FluxerSourceRuntimeConfig, *, factory: FluxerHttpClientFactory | None = None) -> None:
        self._config = config
        self._factory = factory or FluxerHttpClientFactory()
        self._loop = asyncio.new_event_loop()
        self._closed = False
        http = self._factory.create(
            FluxerClientConfig(
                token=config.token,
                is_bot=True,
                api_url=config.api_url,
                max_retries=config.max_retries,
                retry_forever=config.retry_forever,
            )
        )
        self._http = http
        self.adapter = FluxerSourceAdapter(
            FluxerHttpSourceClient(
                http,
                token=config.token,
                emoji_asset_base_url=config.emoji_asset_base_url,
            ),
            config.guild_ids,
            runner=self._loop.run_until_complete,
        )

    @property
    def input_scope(self) -> tuple[str, ...]:
        return self._config.guild_ids

    def import_to_archive(
        self,
        archive_paths: ArchivePaths,
        *,
        resume: bool = False,
        on_status: Callable[[ImportProgress], None] | None = None,
        between_messages_seconds: float = 0.0,
        between_channels_seconds: float = 0.0,
    ) -> ImportReport:
        if self._closed:
            raise AdapterError("Cannot import from a closed Fluxer source runtime.")
        kwargs: dict[str, Any] = {"resume": resume, "on_status": on_status}
        if between_messages_seconds or between_channels_seconds:
            kwargs.update(
                between_messages_seconds=between_messages_seconds,
                between_channels_seconds=between_channels_seconds,
            )
        return CanonicalImportCoordinator(archive_paths).run(self.adapter, **kwargs)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._loop.run_until_complete(self._http.close())
        except AttributeError:
            pass
        finally:
            self._loop.close()

    def __enter__(self) -> "FluxerSourceRuntime":
        if self._closed:
            raise AdapterError("Fluxer source runtime is closed.")
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def build_fluxer_source_runtime_config(
    credentials: Any,
    scope: tuple[str, ...],
    overrides: Mapping[str, Any],
) -> FluxerSourceRuntimeConfig:
    token = overrides.get("token") or getattr(credentials, "fluxer_token", None)
    if not token:
        raise AdapterError("Fluxer source credentials are missing.")
    if not scope or any(not str(value).strip() for value in scope):
        raise AdapterError("Fluxer source scope must contain at least one server ID.")
    return FluxerSourceRuntimeConfig(
        token=str(token),
        guild_ids=tuple(str(value) for value in scope),
        api_url=overrides.get("api_url"),
        emoji_asset_base_url=overrides.get("emoji_asset_base_url"),
        max_retries=int(overrides.get("max_retries", 4)),
        retry_forever=bool(overrides.get("retry_forever", False)),
    )
