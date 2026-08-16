from pathlib import Path

import pytest

from archive_sync_engine.sync.runtime_request import SyncRuntimeRequest


def test_runtime_request_normalizes_adapter_names_and_archive_path(tmp_path: Path) -> None:
    request = SyncRuntimeRequest(
        input_adapter=" Discord ",
        input_scope=("guild",),
        destination_adapter=" Fluxer ",
        destination_scope=("server",),
        archive_path=tmp_path / "archive",
        adapter_config={"discord": object()},
    )

    assert request.input_adapter == "discord"
    assert request.destination_adapter == "fluxer"
    assert request.archive_path == (tmp_path / "archive").resolve()
    assert request.input_scope == ("guild",)


def test_runtime_request_rejects_empty_adapter() -> None:
    with pytest.raises(ValueError, match="Input adapter"):
        SyncRuntimeRequest(
            input_adapter=" ",
            input_scope=("guild",),
            destination_adapter="fluxer",
            destination_scope=("server",),
            archive_path=Path("archive"),
            adapter_config={},
        )


def test_runtime_request_rejects_empty_scope() -> None:
    with pytest.raises(ValueError, match="scope"):
        SyncRuntimeRequest(
            input_adapter="discord",
            input_scope=("",),
            destination_adapter="fluxer",
            destination_scope=("server",),
            archive_path=Path("archive"),
            adapter_config={},
        )


def test_runtime_request_copies_adapter_configuration() -> None:
    config = {"discord": object()}
    request = SyncRuntimeRequest(
        input_adapter="discord",
        input_scope=("guild",),
        destination_adapter="fluxer",
        destination_scope=("server",),
        archive_path=Path("archive"),
        adapter_config=config,
    )

    config["extra"] = object()
    assert "extra" not in request.adapter_config
