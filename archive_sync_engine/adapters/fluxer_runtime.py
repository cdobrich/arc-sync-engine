"""Runtime construction and lifecycle for Fluxer REST destination clients.

The synchronization engine talks to a synchronous ``DestinationAdapter``
interface, while ``fluxer.py`` exposes an asynchronous REST client.  This
module owns the application-level translation between those two boundaries.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable

from .destination import DestinationAdapter
from .exceptions import AdapterError
from .fluxer import FluxerDestinationAdapter, FluxerIdentityMapping


@dataclass(frozen=True, slots=True)
class FluxerClientConfig:
    """Configuration for one authenticated Fluxer REST client."""

    token: str
    is_bot: bool = True
    api_url: str | None = None
    max_retries: int = 4
    retry_forever: bool = False

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("Fluxer client token must not be empty.")
        if self.max_retries < 0:
            raise ValueError("Fluxer max_retries must be non-negative.")


class FluxerHttpClientFactory:
    """Construct authenticated ``fluxer.py`` REST clients."""

    def __init__(
        self,
        *,
        importer: Callable[[], ModuleType] | None = None,
    ) -> None:
        self._importer = importer or self._import_fluxer

    def create(self, config: FluxerClientConfig) -> Any:
        """Create one unopened authenticated Fluxer REST client."""

        module = self._load_fluxer()
        http_client_type = getattr(module, "HTTPClient", None)
        if http_client_type is None:
            raise AdapterError(
                "The installed fluxer.py package does not expose HTTPClient."
            )

        kwargs: dict[str, Any] = {
            "is_bot": config.is_bot,
            "max_retries": config.max_retries,
            "retry_forever": config.retry_forever,
        }
        if config.api_url is not None:
            kwargs["api_url"] = config.api_url

        try:
            return http_client_type(config.token, **kwargs)
        except Exception as exc:
            raise AdapterError(
                "Failed to construct the Fluxer REST client."
            ) from exc

    def _load_fluxer(self) -> ModuleType:
        try:
            return self._importer()
        except Exception as exc:
            raise AdapterError(
                "The optional fluxer.py dependency could not be imported."
            ) from exc

    @staticmethod
    def _import_fluxer() -> ModuleType:
        import fluxer

        return fluxer


class FluxerHttpDestinationClient:
    """Adapt one ``fluxer.py.HTTPClient`` to the engine's Fluxer client shape.

    The adapter deliberately keeps this wrapper platform-specific.  The core
    ``DestinationAdapter`` continues to receive only the project-level
    destination contract.
    """

    def __init__(self, http_client: Any, *, guild_id: str) -> None:
        self._http = http_client
        self._guild_id = guild_id

    async def _create_fluxer_channel_from_discord(
        self,
        channel_data: dict[str, Any],
    ) -> Any:
        return await self._http.create_guild_channel(
            self._guild_id,
            name=str(channel_data["name"]),
            type=int(channel_data["type"]),
        )

    async def send_message(
        self,
        channel_id: str,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
        max_retries: int = 3,
        author_name: str | None = None,
        reply_to_id: str | None = None,
    ) -> dict[str, Any] | None:
        del max_retries
        del author_name

        message_reference = None
        if reply_to_id is not None:
            message_reference = {
                "message_id": reply_to_id,
                "channel_id": channel_id,
            }

        return await self._http.send_message(
            channel_id,
            content=content,
            files=attachments,
            message_reference=message_reference,
        )

    async def edit_message(
        self,
        channel_id: str,
        message_id: str,
        new_content: str,
        new_attachments: list[Any] | None = None,
        max_retries: int = 3,
    ) -> bool:
        del new_attachments
        del max_retries
        await self._http.edit_message(
            channel_id,
            message_id,
            content=new_content,
        )
        return True

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
        max_retries: int = 3,
    ) -> bool:
        del max_retries
        await self._http.delete_message(channel_id, message_id)
        return True

    async def delete_channel(self, channel_id: str) -> bool:
        await self._http.delete_channel(channel_id)
        return True

    async def apply_reaction(
        self,
        channel_id: str,
        message_id: str,
        emoji: str,
        auth_key: str | None = None,
    ) -> bool:
        del auth_key
        await self._http.add_reaction(channel_id, message_id, emoji)
        return True

    async def remove_reaction(
        self,
        channel_id: str,
        message_id: str,
        emoji_id_or_name: str,
        user_id: str = "@me",
        auth_key: str | None = None,
    ) -> bool:
        del auth_key
        await self._http.delete_reaction(
            channel_id,
            message_id,
            emoji_id_or_name,
            user_id=user_id,
        )
        return True

    async def pin_message(
        self,
        channel_id: str,
        message_id: str,
        max_retries: int = 3,
    ) -> bool:
        del max_retries
        await self._http.pin_message(channel_id, message_id)
        return True

    async def unpin_message(
        self,
        channel_id: str,
        message_id: str,
        max_retries: int = 3,
    ) -> bool:
        del max_retries
        await self._http.unpin_message(channel_id, message_id)
        return True

    async def remove_attachment(
        self,
        channel_id: str,
        message_id: str,
        filename: str,
    ) -> bool:
        """Remove one existing message attachment safely.

        The current fluxer.py wrapper exposes message retrieval and a generic
        authenticated request API, but not a dedicated attachment-removal
        helper. Fluxer's message PATCH API accepts the retained attachment
        set, so the runtime fetches the current message, identifies a unique
        attachment by filename, and patches the message with every attachment
        except that one. Ambiguous matches are rejected rather than removing
        an arbitrary attachment.
        """
        message = await self._http.get_message(channel_id, message_id)
        attachments = list(message.get("attachments") or [])
        matches = [
            attachment
            for attachment in attachments
            if str(attachment.get("filename", "")) == filename
        ]
        if len(matches) > 1:
            raise AdapterError(
                f"Fluxer message {message_id!r} contains multiple attachments "
                f"named {filename!r}; removal is ambiguous."
            )
        if not matches:
            return True

        retained = [
            {
                "id": str(attachment["id"]),
                **({"filename": attachment["filename"]} if attachment.get("filename") else {}),
            }
            for attachment in attachments
            if attachment is not matches[0]
        ]
        route = self._http._route(
            "PATCH",
            "/channels/{channel_id}/messages/{message_id}",
            channel_id=channel_id,
            message_id=message_id,
        )
        await self._http.request(
            route,
            json={"attachments": retained},
        )
        return True

    async def close(self) -> None:
        await self._http.close()


class FluxerDestinationRuntime:
    """Own the real Fluxer REST clients used by one destination adapter.

    The bot client is created eagerly.  User clients are created lazily only
    when a canonical identity mapping actually requires masquerading.
    """

    @classmethod
    def from_destination_runtime_request(
        cls, request: "DestinationRuntimeRequest"
    ) -> "FluxerDestinationRuntime":
        """Construct the Fluxer destination runtime from an adapter-neutral request."""
        from archive_sync_engine.adapters.destination_runtime_request import DestinationRuntimeRequest

        if request.adapter != "fluxer":
            raise AdapterError(
                "FluxerDestinationRuntime requires the fluxer destination adapter."
            )
        try:
            config = request.adapter_config["fluxer"]
        except KeyError as exc:
            raise AdapterError(
                "Missing runtime configuration for adapter 'fluxer'."
            ) from exc
        if not isinstance(config, FluxerClientConfig):
            raise AdapterError("Runtime configuration for 'fluxer' is invalid.")
        if len(request.scope) != 1:
            raise AdapterError("Fluxer destination scope must contain exactly one server ID.")
        identity_mappings = tuple(request.adapter_config.get("identity_mappings", ()))
        return cls(
            guild_id=request.scope[0],
            bot_client=config,
            identity_mappings=identity_mappings,
            client_factory=request.adapter_config.get("fluxer_client_factory"),
        )

    def __init__(
        self,
        *,
        guild_id: str,
        bot_client: FluxerClientConfig,
        identity_mappings: tuple[FluxerIdentityMapping, ...] = (),
        client_factory: FluxerHttpClientFactory | None = None,
    ) -> None:
        if not guild_id:
            raise ValueError("Fluxer guild_id must not be empty.")

        self._guild_id = guild_id
        self._factory = client_factory or FluxerHttpClientFactory()
        self._bot_config = bot_client
        self._identity_mappings = identity_mappings
        self._http_clients: list[Any] = []
        self._closed = False

        bot_http = self._factory.create(bot_client)
        self._http_clients.append(bot_http)
        self._bot_client = FluxerHttpDestinationClient(
            bot_http,
            guild_id=guild_id,
        )

        mapping_by_name = {mapping.username: mapping for mapping in identity_mappings}
        self._mapping_by_name = mapping_by_name
        self._identity_clients: dict[str, FluxerHttpDestinationClient] = {}

        self._adapter = FluxerDestinationAdapter(
            self._bot_client,
            identity_mappings=identity_mappings,
            identity_client_factory=self._create_identity_client,
        )

    @property
    def adapter(self) -> DestinationAdapter:
        return self._adapter

    def _create_identity_client(
        self,
        mapping: FluxerIdentityMapping,
    ) -> FluxerHttpDestinationClient:
        if mapping.fluxer_auth_key is None:
            return self._bot_client

        cached = self._identity_clients.get(mapping.username)
        if cached is not None:
            return cached

        if self._closed:
            raise AdapterError(
                "Cannot create a Fluxer identity client after the runtime "
                "has been closed."
            )

        config = FluxerClientConfig(
            token=mapping.fluxer_auth_key,
            is_bot=False,
            api_url=self._bot_config.api_url,
            max_retries=self._bot_config.max_retries,
            retry_forever=self._bot_config.retry_forever,
        )
        http_client = self._factory.create(config)
        self._http_clients.append(http_client)
        client = FluxerHttpDestinationClient(
            http_client,
            guild_id=self._guild_id,
        )
        self._identity_clients[mapping.username] = client
        return client

    def close(self) -> None:
        """Close all owned HTTP clients.

        The engine's application boundary is synchronous today.  Like the
        destination adapter, this method must be called outside a running
        asyncio event loop.
        """
        if self._closed:
            return
        self._closed = True

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            for client in reversed(self._http_clients):
                asyncio.run(client.close())
            return

        self._closed = False
        raise RuntimeError(
            "FluxerDestinationRuntime.close() cannot run inside an active "
            "asyncio event loop."
        )
