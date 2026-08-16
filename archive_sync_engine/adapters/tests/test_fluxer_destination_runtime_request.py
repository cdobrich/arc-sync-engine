from pathlib import Path

import pytest

from archive_sync_engine.adapters import AdapterError, DestinationRuntimeRequest
from archive_sync_engine.adapters.fluxer_runtime import (
    FluxerClientConfig,
    FluxerDestinationRuntime,
)


def test_fluxer_destination_runtime_factory_uses_adapter_neutral_request(
    tmp_path: Path,
) -> None:
    class FakeFactory:
        def __init__(self) -> None:
            self.configs = []

        def create(self, config: FluxerClientConfig):
            self.configs.append(config)
            return FakeHttpClient()

    class FakeHttpClient:
        async def close(self) -> None:
            pass

    factory = FakeFactory()
    config = FluxerClientConfig(token="fluxer-token")
    request = DestinationRuntimeRequest(
        adapter="fluxer",
        scope=("server-1",),
        archive_path=tmp_path,
        adapter_config={
            "fluxer": config,
            "fluxer_client_factory": factory,
        },
    )

    runtime = FluxerDestinationRuntime.from_destination_runtime_request(request)
    try:
        assert runtime.adapter is not None
        assert factory.configs == [config]
    finally:
        runtime.close()


def test_fluxer_destination_runtime_factory_rejects_invalid_adapter(
    tmp_path: Path,
) -> None:
    request = DestinationRuntimeRequest(
        adapter="discord",
        scope=("server-1",),
        archive_path=tmp_path,
        adapter_config={},
    )

    with pytest.raises(AdapterError, match="requires the fluxer"):
        FluxerDestinationRuntime.from_destination_runtime_request(request)


def test_fluxer_destination_runtime_factory_requires_one_server_scope(
    tmp_path: Path,
) -> None:
    request = DestinationRuntimeRequest(
        adapter="fluxer",
        scope=("server-1", "server-2"),
        archive_path=tmp_path,
        adapter_config={"fluxer": FluxerClientConfig(token="fluxer-token")},
    )

    with pytest.raises(AdapterError, match="exactly one server"):
        FluxerDestinationRuntime.from_destination_runtime_request(request)
