from pathlib import Path

import pytest

from archive_sync_engine.adapters import DestinationRuntimeRequest


def test_destination_runtime_request_normalizes_adapter_and_copies_config(tmp_path: Path) -> None:
    config = {"token": "secret"}
    request = DestinationRuntimeRequest(
        adapter=" Fluxer ",
        scope=("server-1",),
        archive_path=tmp_path,
        adapter_config=config,
    )

    config["other"] = "value"

    assert request.adapter == "fluxer"
    assert request.scope == ("server-1",)
    assert request.archive_path == tmp_path.resolve()
    assert request.adapter_config == {"token": "secret"}


def test_destination_runtime_request_rejects_empty_adapter(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="adapter name"):
        DestinationRuntimeRequest("   ", ("server-1",), tmp_path, {})


def test_destination_runtime_request_rejects_empty_scope(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="scope values"):
        DestinationRuntimeRequest("fluxer", ("",), tmp_path, {})
