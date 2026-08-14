"""Runtime construction for authenticated Fluxer REST clients.

The synchronization engine uses the Fluxer REST surface synchronously through
its destination adapter.  The upstream ``fluxer.py`` package exposes both a
higher-level gateway ``Client`` and the lower-level ``HTTPClient``.  This
module deliberately constructs the latter so the destination adapter does not
start or own a WebSocket gateway merely to execute REST operations.

The dependency is imported lazily so the core Archive-Sync Engine remains
usable without installing the optional Fluxer integration dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable

from .exceptions import AdapterError


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
    """Construct authenticated ``fluxer.py`` REST clients.

    ``fluxer.py`` keeps authentication on ``HTTPClient`` itself: bot tokens
    receive the ``Bot `` authorization prefix while user tokens are sent as
    user credentials.  This factory preserves that distinction for the
    destination adapter's actor selection logic.
    """

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
