from pathlib import Path

import pytest

from archive_sync_engine.adapters import SourceRuntimeRequest


def test_source_runtime_request_normalizes_adapter_and_copies_config(tmp_path: Path) -> None:
    config = {"token": "secret"}
    request = SourceRuntimeRequest(
        adapter=" Discord ",
        scope=("123",),
        archive_path=tmp_path,
        adapter_config=config,
    )

    config["other"] = "value"

    assert request.adapter == "discord"
    assert request.scope == ("123",)
    assert request.archive_path == tmp_path.resolve()
    assert request.adapter_config == {"token": "secret"}


def test_source_runtime_request_rejects_empty_adapter(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="adapter name"):
        SourceRuntimeRequest("   ", ("123",), tmp_path, {})


def test_source_runtime_request_rejects_empty_scope(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="scope values"):
        SourceRuntimeRequest("discord", ("",), tmp_path, {})
