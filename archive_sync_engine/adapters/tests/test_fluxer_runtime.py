from __future__ import annotations

from types import SimpleNamespace

import pytest

from archive_sync_engine.adapters.exceptions import AdapterError
from archive_sync_engine.adapters.fluxer_runtime import (
    FluxerClientConfig,
    FluxerHttpClientFactory,
)


def test_fluxer_runtime_constructs_bot_http_client() -> None:
    calls: list[tuple[str, dict]] = []

    class FakeHTTPClient:
        def __init__(self, token: str, **kwargs) -> None:
            calls.append((token, kwargs))

    factory = FluxerHttpClientFactory(
        importer=lambda: SimpleNamespace(HTTPClient=FakeHTTPClient),
    )

    client = factory.create(
        FluxerClientConfig(
            token="bot-token",
            is_bot=True,
            api_url="https://fluxer.example/v1",
            max_retries=7,
            retry_forever=True,
        )
    )

    assert isinstance(client, FakeHTTPClient)
    assert calls == [
        (
            "bot-token",
            {
                "is_bot": True,
                "api_url": "https://fluxer.example/v1",
                "max_retries": 7,
                "retry_forever": True,
            },
        ),
    ]


def test_fluxer_runtime_constructs_user_http_client_without_gateway() -> None:
    calls: list[tuple[str, dict]] = []

    class FakeHTTPClient:
        def __init__(self, token: str, **kwargs) -> None:
            calls.append((token, kwargs))

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("gateway Client must not be constructed")

    factory = FluxerHttpClientFactory(
        importer=lambda: SimpleNamespace(
            HTTPClient=FakeHTTPClient,
            Client=FakeClient,
        ),
    )

    factory.create(
        FluxerClientConfig(
            token="user-token",
            is_bot=False,
        )
    )

    assert calls == [
        (
            "user-token",
            {
                "is_bot": False,
                "max_retries": 4,
                "retry_forever": False,
            },
        ),
    ]


def test_fluxer_runtime_reports_missing_dependency_as_adapter_error() -> None:
    factory = FluxerHttpClientFactory(
        importer=lambda: (_ for _ in ()).throw(ImportError("missing")),
    )

    with pytest.raises(AdapterError, match="fluxer.py dependency"):
        factory.create(
            FluxerClientConfig(
                token="bot-token",
            )
        )


def test_fluxer_runtime_rejects_empty_token() -> None:
    with pytest.raises(ValueError, match="token"):
        FluxerClientConfig(token="")
