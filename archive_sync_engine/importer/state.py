"""
Importer state model.

ImportState represents importer-specific progress that can be persisted
and later restored.

The contents of the state are intentionally opaque to the engine.

Only the Importer implementation that created the state is expected to
interpret its contents.

The ImportCoordinator is responsible for persisting and restoring the
state but never examines the payload itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ImportState:
    """
    Opaque importer-owned progress state.

    The payload is entirely owned by the Importer implementation.
    Different SourceAdapters may store completely different information.
    """

    payload: Mapping[str, Any]
