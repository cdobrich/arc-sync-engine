from __future__ import annotations

import pytest

from archive_sync_engine.sync.state_namespace import destination_state_namespace


def test_destination_state_namespace_is_adapter_and_scope_specific() -> None:
    assert destination_state_namespace("Fluxer", ("1539964012871808",)) == (
        "fluxer:1539964012871808"
    )


def test_destination_state_namespace_supports_multiple_scope_values() -> None:
    assert destination_state_namespace("adapter", ("one", "two")) == "adapter:one/two"


@pytest.mark.parametrize("adapter,scope", [("", ("1",)), ("fluxer", ()), ("fluxer", ("",))])
def test_destination_state_namespace_rejects_invalid_scope(adapter: str, scope: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        destination_state_namespace(adapter, scope)
